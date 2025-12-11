Inspired by this post https://www.reddit.com/r/AskPhotography/comments/1pjoiuc/how_do_i_achieve_this_effect/

Used ChatGPT 5.1 to generate, see conversation: https://chatgpt.com/share/693a5b90-0bfc-800b-aa56-59bb6f2a486f

Specifications:

From the command line, the user specifies

 * path to a video file
 * optionally: start time and duration within the video file, default to full length, must allow inputs more precise than just seconds
 * optionally: cropping rectangle within the video, default to full size
 * optionally: stack count, default to 5
 * optionally: interval, default to 5
 * optionally: opacity table, a list of integers, default to none (none means auto generate)
 * optionally: loop count, default to 1
 * optionally: path to FFMPEG executable, default to some expected location
 * optionally: temp path for input frames, default to "temp_input_frames"
 * optionally: temp path for output frames, default to "temp_output_frames"
 * optionally: output video path, default to "output.mp4" 
 * optionally: string with args to be passed to FFMPEG during file generation, default to something that encodes h.264 (you might need to help me make this smarter)

Expect for me to have opencv and pillow and numpy installed, suggest other libraries as needed

The script will open the video file with FFMPEG, learn its dimensions and its frame rate (and other meta data as needed).

Using FFMPEG, split the video into PNG frames, from the specified start time and for the specified duration. Crop each frame according to the specified cropping rectangle. Save the frames in a directory for temporary input frames (delete and recreate the directory every time the script starts), with numerically sequencial file names (these names will be used later to reassemble back into a video, so format it in a way that makes this easy).

Examine the opacity table if it is not None, the table length must match the stack count (if not, throw an exception). Sum up the table. This sum is actually used to calculate the true opacity when we start to actually stack (alpha blend) the frames, as the value in the table is actually relative to this sum, not an absolute number.

If the opacity table is None, generate it, it should be as long as the stack count, it should represent a bell curve but add 1 to all values to prevent zero.

For every frame, for example, frame 1 with the default count and interval, take the 1st, 6th, 11th, 16th, and 21th frames, alpha-blend them, the alpha value uses the corresponding entry in the opacity table. Then for frame 2, it uses 2nd 7th 12th 17th and 22th frames, and the same table.

This behavior has to wrap when reaching the end of the sequence

The frames are saved to the temporary output frames path (delete and recreate the directory every time the script starts). The file names must be sequencial and matching the input file name.

Use FFMPEG to create a video using the output frames, respect the original frame rate, the output file format should try to respect the user's desired file extension. Use the user's specified additional args for FFMPEG. It should loop the number of times the user specifies (but 0 means 1, and 1 means no loop).
