I'm trying to help this guy https://www.reddit.com/r/AskPhotography/comments/1nbfngu/is_there_a_simpler_way_to_do_it/

Prompt to ChatGPT: (actual chat https://chatgpt.com/share/68be7563-bed0-800b-bba2-67d32e5e7ef0)

I need a python script.

Using argparse, allow the user to specify a directory, a total number, an interval number (default to 1), an angle (degrees, default to 90), and an output file (default to `output.png`)

The files in the directory, filter only JPG and PNG files, sort them by file name. They are all photos from a timelapse sequence. Generate a list using the interval parameter, 1 or 0 means every file, 2 means skip every 1 file, etc, until the list is as long as the total number the user specified.

this probably involves Pillow and/or cv2, maybe others. Assume I have them installed but give me a list of libraries/modules

Use the first photo in the list to know the dimension of the photo.

Create a blank canvas using that dimension

For angles 0, 90, 180, and 270, the logic is simple. I'll use 90 as an example, 90 degrees points right, meaning "from left to right". In this example, pretend the dimension is 1000 wide by 800 high, and we use 100 total files. From the first file, slice the column X=0 to x=9 and copy it to the canvas at the left most edge of the canvas, the 2nd file will be sliced from columns x=10 to x=19 and copied to the canvas at X=10. The last file will be X = 990 to X = 999. Note that if there's any leftover parts of the canvas that's not written due to rounding error, shrink the canvas.

Angle 270 would mean from "right to left", 0 means "bottom to top", 180 means "top to bottom".

For all other angles, this is where you, my AI friend, gets to be smart and help me out. It will probably involve diagonal slices but make sure there are no tiny gaps where the edges meet.

Output to the file path that the user specified, respect the user's choice of file extension as much as possible.
