import os
import warnings
from moviepy import VideoFileClip # Corrected import
import whisper
import sys
import argparse
from pydub import AudioSegment
from tkinter import Tk
from tkinter.filedialog import askopenfilenames # Changed import
import traceback # For error handling

# --- Helper Functions (Unchanged) ---

def remove_duplicate_segment(sentences, duplicate_duration):
    """Remove subtitles from duplicated segment at the beginning and adjust timestamps."""
    adjusted_segments = []
    for segment in sentences:
        # Skip segments that *end* within the duplicate duration
        # or start exactly at the duplicate duration (edge case)
        if segment['end'] <= duplicate_duration:
            continue
        # Adjust segments that *start* within the duplicate duration but end after it
        elif segment['start'] < duplicate_duration:
             adjusted_segment = segment.copy()
             # Keep the part of the text that occurs after the duplicate duration
             # This is an approximation, Whisper segments might not align perfectly
             # A simpler approach is just to skip these partial segments too,
             # but let's try adjusting start time.
             adjusted_segment['start'] = 0 # Start immediately after duplicate ends
             adjusted_segment['end'] -= duplicate_duration
             # Optional: Add a check if the adjusted duration is too small
             if adjusted_segment['end'] > adjusted_segment['start']:
                 adjusted_segments.append(adjusted_segment)
        # Adjust segments that start after the duplicate duration
        else:
            adjusted_segment = segment.copy()
            adjusted_segment['start'] -= duplicate_duration
            adjusted_segment['end'] -= duplicate_duration
            adjusted_segments.append(adjusted_segment)
    return adjusted_segments


def dict_to_srt(subtitles):
    """Convert Whisper output to SRT format."""
    srt_string = ""
    # Filter out any segments with negative or invalid times after adjustment
    valid_subtitles = [s for s in subtitles if s.get('start') is not None and s.get('end') is not None and s['start'] >= 0 and s['end'] > s['start']]

    for index, subtitle in enumerate(valid_subtitles):
        start_time = subtitle["start"]
        # Use pre-calculated end time if available, otherwise estimate
        end_time = subtitle.get("end")
        # Ensure end_time is valid and after start_time
        if end_time is None or end_time <= start_time:
             end_time = estimate_end_time(start_time, subtitle["text"])
             # Double check estimation didn't create overlap issue (though unlikely here)
             if end_time <= start_time:
                 end_time = start_time + 1 # Add a minimal duration like 1 second

        srt_string += f"{index + 1}\n{format_time(start_time)} --> {format_time(end_time)}\n{subtitle['text'].strip()}\n\n"
    return srt_string

def format_time(timestamp):
    """Convert timestamp to SRT time format."""
    # Ensure timestamp is not negative before processing
    timestamp = max(0, timestamp)
    hours, remainder = divmod(timestamp, 3600)
    minutes, seconds = divmod(remainder, 60)
    milliseconds = int((seconds % 1) * 1000)
    return "{:02}:{:02}:{:02},{:03}".format(int(hours), int(minutes), int(seconds), milliseconds)

def estimate_end_time(start_time, text, words_per_minute=100):
    """Estimate end time based on text length. Ensures end time is after start time."""
    word_count = len(text.split())
    # Avoid division by zero or negative duration if text is empty
    if word_count == 0:
        return start_time + 1 # Assign a minimal duration (e.g., 1 second)
    duration_in_seconds = max(0.5, (word_count / words_per_minute) * 60) # Ensure a minimum duration
    return start_time + duration_in_seconds

# --- Main Processing Function for a Single Video ---
def process_video(video_file, language, model, skip_preview=False):
    """Processes a single video file for transcription with two-stage approach."""
    print(f"\n--- Processing: {os.path.basename(video_file)} ---")
    script_dir = os.path.dirname(os.path.abspath(video_file)) # Save SRT next to video
    base_filename = os.path.splitext(os.path.basename(video_file))[0]

    # Use unique temp names based on video, or place in a dedicated temp folder
    # For simplicity, placing next to video with unique prefix
    temp_audio_file = os.path.join(script_dir, f"_temp_dup_{base_filename}.wav")
    audio_file = os.path.join(script_dir, f"_temp_extracted_{base_filename}.wav")
    audio_5min_file = os.path.join(script_dir, f"_temp_10min_{base_filename}.wav")
    srt_filename = os.path.join(script_dir, base_filename + ".srt")
    srt_5min_filename = os.path.join(script_dir, base_filename + "_10min.srt")

    audio_duration = 0 # Initialize
    duplication_performed = False # Flag to track duplication

    try:
        # Step 1: Check video duration first
        print("Checking video duration...")
        with VideoFileClip(video_file) as video:
            if video.audio is None:
                print(f"Error: Video file '{os.path.basename(video_file)}' has no audio track. Skipping.")
                return # Skip this file
            audio_duration = video.duration  # Duration in seconds
            print(f"Video duration: {audio_duration:.2f} seconds")
            
            # Step 2: Extract and process based on duration
            if audio_duration > 600 and not skip_preview:  # If longer than 10 minutes and preview not skipped
                print("Extracting first 10 minutes for quick transcription...")
                # Extract only first 10 minutes initially
                audio_5min = video.audio.subclipped(0, 600)  # 0 to 10 minutes
                audio_5min.write_audiofile(audio_5min_file, codec='pcm_s16le')
                
                # Step 3a: Quick transcription of first 10 minutes
                print("Starting quick transcription of first 10 minutes...")
                transcription_5min = model.transcribe(audio_5min_file, language=language, verbose=False, condition_on_previous_text=False)
                sentences_5min = transcription_5min['segments']
                print("Quick transcription finished.")
                
                # Step 4a: Save 10-minute SRT for immediate viewing
                print("Converting 10-minute transcription to SRT format...")
                srt_output_5min = dict_to_srt(sentences_5min)
                with open(srt_5min_filename, "w", encoding="utf-8") as file:
                    file.write(srt_output_5min)
                print(f"10-minute preview subtitles saved to {srt_5min_filename}")
                print("\n*** You can now start watching with the 10-minute preview subtitles! ***")
                print("*** Full transcription will continue in the background... ***\n")
                
                # Now extract full audio for complete transcription
                print("Extracting full audio for complete transcription...")
                audio = video.audio
                audio.write_audiofile(audio_file, codec='pcm_s16le')
                print("Full audio extracted successfully.")
            elif audio_duration > 600 and skip_preview:
                print("Skipping 10-minute preview as requested, extracting full audio...")
                audio = video.audio
                audio.write_audiofile(audio_file, codec='pcm_s16le')
                print("Full audio extracted successfully.")
            else:
                print("Video is 10 minutes or shorter, extracting full audio...")
                audio = video.audio
                audio.write_audiofile(audio_file, codec='pcm_s16le')
                print("Audio extracted successfully.")

        # Step 3: Handle short audio duplication if needed
        # Use audio_file directly for transcription unless duplication is needed
        transcribe_target_file = audio_file

        if 0 < audio_duration < 30: # Check if duration is positive but less than 30 seconds
            print("Audio duration is less than 30 seconds. Duplicating middle 10s to improve detection.")
            # Load the audio segment for duplication
            audio_segment = AudioSegment.from_file(audio_file)
            
            # Calculate middle chunk ensuring it stays within bounds
            middle_duration_ms = 10000 # 10 seconds in milliseconds
            audio_duration_ms = audio_duration * 1000

            # Ensure middle chunk doesn't exceed audio length
            actual_middle_duration_ms = min(middle_duration_ms, audio_duration_ms)

            middle_start_ms = max(0, (audio_duration_ms / 2) - (actual_middle_duration_ms / 2))
            middle_end_ms = middle_start_ms + actual_middle_duration_ms

            # Ensure end doesn't exceed duration
            middle_end_ms = min(middle_end_ms, audio_duration_ms)
            # Recalculate start if end was capped
            middle_start_ms = max(0, middle_end_ms - actual_middle_duration_ms)

            print(f"Duplicating segment from {middle_start_ms/1000:.2f}s to {middle_end_ms/1000:.2f}s")

            middle_chunk = audio_segment[middle_start_ms:middle_end_ms]
            duplicated_audio = middle_chunk + audio_segment # Prepend the chunk
            duplicated_audio.export(temp_audio_file, format="wav") # Export as WAV for consistency
            transcribe_target_file = temp_audio_file # Transcribe the duplicated file
            duplication_performed = True
            duplicate_duration = len(middle_chunk) / 1000 # Actual duration of the prepended chunk
            print(f"Duplicated segment duration: {duplicate_duration:.2f} seconds")
        else:
            print("Audio duration is sufficient or zero. No duplication needed.")
            duplicate_duration = 0 # Ensure it's defined

        # Step 3b: Transcribe full audio with Whisper
        print("Starting full transcription...")
        transcription = model.transcribe(transcribe_target_file, language=language, verbose=False, condition_on_previous_text=False) # Original simpler call
        sentences = transcription['segments']
        print("Full transcription finished.")

        # Step 4b: Adjust transcription if duplication was performed
        if duplication_performed and duplicate_duration > 0:
            print("Adjusting timestamps due to duplication...")
            sentences = remove_duplicate_segment(sentences, duplicate_duration)
            print("Timestamps adjusted.")
        elif duplication_performed:
             print("Duplication was marked but duplicate duration is zero. Skipping adjustment.")


        # Step 5: Convert full transcription to SRT format
        print("Converting full transcription to SRT format...")
        srt_output = dict_to_srt(sentences)

        with open(srt_filename, "w", encoding="utf-8") as file:
            file.write(srt_output)
        print(f"Full processing completed. Complete subtitles saved to {srt_filename}")
        
        # Clean up 10-minute preview file if it exists
        if os.path.exists(srt_5min_filename):
            try:
                os.remove(srt_5min_filename)
                print(f"Removed 10-minute preview file: {os.path.basename(srt_5min_filename)}")
            except OSError as e:
                print(f"Note: Could not remove 10-minute preview file {srt_5min_filename}: {e}")

    except Exception as e:
        print(f"\n--- ERROR processing {os.path.basename(video_file)} ---")
        print(f"An error occurred: {e}")
        traceback.print_exc() # Print detailed traceback
        print("--------------------------------------------------")

    finally:
        # Cleanup temporary files
        if duplication_performed and os.path.exists(temp_audio_file):
            try:
                os.remove(temp_audio_file)
                print(f"Deleted temporary duplicated audio: {os.path.basename(temp_audio_file)}")
            except OSError as e:
                print(f"Error deleting temporary file {temp_audio_file}: {e}")
        if os.path.exists(audio_file):
            try:
                os.remove(audio_file)
                print(f"Deleted temporary extracted audio: {os.path.basename(audio_file)}")
            except OSError as e:
                print(f"Error deleting temporary file {audio_file}: {e}")
        if os.path.exists(audio_5min_file):
            try:
                os.remove(audio_5min_file)
                print(f"Deleted temporary 10-minute audio: {os.path.basename(audio_5min_file)}")
            except OSError as e:
                print(f"Error deleting temporary file {audio_5min_file}: {e}")


# --- Script Execution ---
if __name__ == "__main__":
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Generate subtitles for video files using Whisper')
    parser.add_argument('language', nargs='?', default='de', help='Language code for transcription (e.g., en, es, fr, ja) [default: de]')
    parser.add_argument('--no-preview', action='store_true', help='Skip 10-minute preview transcription for long videos')
    args = parser.parse_args()
    
    # Hide the root Tkinter window
    Tk().withdraw()

    print("Please select one or more video files...")
    # Open file dialog to select multiple files
    video_files = askopenfilenames(
        title="Select Video Files",
        filetypes=[("Video Files", "*.mp4 *.avi *.mov *.mkv *.webm *.flv"), ("All Files", "*.*")]
    ) # Returns a tuple of paths

    if not video_files:
        print("No files selected. Exiting...")
        sys.exit(1)

    print(f"Selected {len(video_files)} file(s).")

    # Use language from command line arguments
    language = args.language
    print(f"Using language: {language}")
    
    if args.no_preview:
        print("10-minute preview disabled - will transcribe full videos directly")

    # Load the Whisper model once
    print("Loading Whisper model...")
    try:
        # Consider using a different model size if 'base' is too slow or 'large' is too resource-intensive
        # Available models: tiny, base, small, medium, large, large-v2, large-v3
        # Add device='cuda' if GPU is available and configured correctly
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=FutureWarning)
            warnings.filterwarnings("ignore", category=UserWarning) # Suppress FP16 warnings if needed
            # Check for CUDA availability if desired
            device = 'cuda' if whisper.torch.cuda.is_available() else 'cpu'
            print(f"Using device: {device}")
            # model = whisper.load_model("base", device=device) # Choose model size
            model = whisper.load_model("turbo", device=device) # Choose model size
            # model = whisper.load_model("turbo", device='cuda') # Keep original if 'turbo' exists and works for you
    except Exception as e:
        print(f"Error loading Whisper model: {e}")
        print("Please ensure Whisper is installed correctly and model files are accessible.")
        if 'cuda' in str(e).lower():
             print("CUDA error detected. Try running with CPU or check your CUDA setup.")
             print("Attempting to load model on CPU...")
             try:
                 model = whisper.load_model("turbo", device='cpu')
                 print("Successfully loaded model on CPU.")
             except Exception as cpu_e:
                 print(f"Failed to load model on CPU as well: {cpu_e}")
                 sys.exit(1)

        else:
            sys.exit(1)
    print("Whisper model loaded successfully.")


    # Process each selected video file
    total_files = len(video_files)
    for i, video_path in enumerate(video_files):
        print(f"\n>>> Processing file {i+1} of {total_files} <<<")
        process_video(video_path, language, model, args.no_preview) # Pass the loaded model and skip_preview flag

    print("\n--- All selected videos processed. ---")