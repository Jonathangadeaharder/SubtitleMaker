import os
from moviepy.editor import VideoFileClip, concatenate_videoclips
import whisper
import torch
import sys
from pydub import AudioSegment

# Main function
def main(video_file, language):
    # Get the absolute path of the current script directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    temp_audio_file = os.path.join(script_dir, "temp_audio_with_duplicate.ogg")
    audio_file = os.path.join(script_dir, "extracted_audio.ogg")

    model = whisper.load_model("turbo", device='cuda')

    # Step 1: Extract audio from the video
    print("Starting audio extraction...")
    with VideoFileClip(video_file) as video:
        audio = video.audio
        audio.write_audiofile(audio_file)
    print("Audio extracted successfully.")

    # Step 2: Check audio duration and decide on duplication
    audio_segment = AudioSegment.from_file(audio_file)
    audio_duration = len(audio_segment) / 1000  # Duration in seconds
    print("audio_duration", audio_duration)
    if audio_duration < 300:  # Duplicate if the audio is <= 5 minutes
        print("Duplicating 10 seconds from the middle...")
        middle_start = max(0, (audio_duration / 2) - 5) * 1000  # Middle point minus 5 seconds in milliseconds
        print("middle_start", middle_start)
        middle_end = min(audio_duration * 1000, middle_start + 10000)  # 10 seconds in milliseconds
        print("middle_end", middle_end)
        middle_chunk = audio_segment[middle_start:middle_end]  # 10-second chunk from the middle
        duplicated_audio = middle_chunk + audio_segment
        duplicated_audio.export(temp_audio_file, format="ogg")
        print("10 seconds from the middle duplicated.")
    else:
        print("Audio duration is above 5 minutes. Skipping duplication...")
        temp_audio_file = audio_file

    # Step 3: Transcribe audio with Whisper
    print("Starting transcription...")
    transcription = model.transcribe(temp_audio_file, language=language, verbose=False, condition_on_previous_text=False)
    sentences = transcription['segments']

    # Step 4: Adjust transcription if duplication was performed
    if audio_duration < 300:
        duplicate_duration = (middle_end - middle_start) / 1000  # Convert to seconds
        print("duplicate_duration", duplicate_duration)
        sentences = remove_duplicate_segment(sentences, duplicate_duration)

    # Step 5: Convert transcription to SRT format
    srt_output = dict_to_srt(sentences)
    srt_filename = os.path.splitext(video_file)[0] + ".srt"

    with open(srt_filename, "w", encoding="utf-8") as file:
        file.write(srt_output)
    print(f"Processing completed. Subtitles saved to {srt_filename}")

    # Cleanup
    if audio_duration < 300 and os.path.exists(temp_audio_file):
        os.remove(temp_audio_file)  # Delete temporary audio file
    if os.path.exists(audio_file):
        os.remove(audio_file)  # Delete extracted audio file

# Remove duplicated segment at the beginning
def remove_duplicate_segment(sentences, duplicate_duration):
    """Remove subtitles from duplicated segment at the beginning and adjust timestamps."""
    adjusted_segments = []
    for segment in sentences:
        print(segment)
        if segment['start'] <= duplicate_duration:
            # Skip segments from the duplicated part at the beginning
            continue
        else:
            # Shift timestamps for segments after the duplicated part
            adjusted_segment = segment.copy()
            adjusted_segment['start'] -= duplicate_duration
            adjusted_segment['end'] -= duplicate_duration
            adjusted_segments.append(adjusted_segment)
            print(adjusted_segment)
    return adjusted_segments

# Helper functions
def dict_to_srt(subtitles):
    """Convert Whisper output to SRT format."""
    srt_string = ""
    for index, subtitle in enumerate(subtitles):
        start_time = subtitle["start"]
        end_time = subtitle.get("end") or estimate_end_time(start_time, subtitle["text"])
        srt_string += f"{index + 1}\n{format_time(start_time)} --> {format_time(end_time)}\n{subtitle['text'].strip()}\n\n"
    return srt_string

def format_time(timestamp):
    """Convert timestamp to SRT time format."""
    hours, remainder = divmod(timestamp, 3600)
    minutes, seconds = divmod(remainder, 60)
    milliseconds = int((seconds % 1) * 1000)
    return "{:02}:{:02}:{:02},{:03}".format(int(hours), int(minutes), int(seconds), milliseconds)

def estimate_end_time(start_time, text, words_per_minute=100):
    """Estimate end time based on text length."""
    word_count = len(text.split())
    duration_in_seconds = (word_count / words_per_minute) * 60
    return start_time + duration_in_seconds

# Run main if script is executed
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python subtitle_script.py <video_file> [language]")
    else:
        video_file = sys.argv[1]
        language = sys.argv[2]
        main(video_file, language)
