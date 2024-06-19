import cv2
import pickle, sys
import numpy as np
sys.path.append('../toolbox/')
from flir_toolbox import *

# Load the IR recording data from the pickle file
data_dir='../../recorded_data/wallbf_100ipm_v10_70ipm_v7/'
# data_dir='../../recorded_data/wall_weld_test/5356_150ipm_2024_06_17_14_36_16/layer_2'
with open(data_dir+'/ir_recording.pickle', 'rb') as file:
    ir_recording = pickle.load(file)
ir_ts=np.loadtxt(data_dir+'/ir_stamps.csv', delimiter=',')


# Create a window to display the images
cv2.namedWindow("IR Recording", cv2.WINDOW_NORMAL)

# Set the colormap (inferno) and normalization range for the color bar
cmap = cv2.COLORMAP_INFERNO

# Function to update the frame
def update_frame(val):
    i = cv2.getTrackbarPos('Frame', 'IR Recording')
    ir_image = np.rot90(ir_recording[i], k=-1)

    ir_normalized = ((ir_image - np.min(ir_image)) / (np.max(ir_image) - np.min(ir_image))) * 255
    ir_normalized=np.clip(ir_normalized, 0, 255)

    # Convert the IR image to BGR format with the inferno colormap
    ir_bgr = cv2.applyColorMap(ir_normalized.astype(np.uint8), cv2.COLORMAP_INFERNO)

    # Display the IR image
    cv2.imshow("IR Recording", ir_bgr)

# Create the trackbars
cv2.createTrackbar('Frame', 'IR Recording', 1, min(len(ir_recording),len(ir_ts)) - 1, update_frame)
cv2.createTrackbar('Play', 'IR Recording', 0, 1, lambda x: None)

# Initialize with the first frame
update_frame(0)

i = 1
while True:
    # Check if the 'Play' trackbar is set to 1 (play)
    if cv2.getTrackbarPos('Play', 'IR Recording') == 1:
        # Increment the frame index
        i = (i + 1) % len(ir_recording)

        # Update the 'Frame' trackbar position
        cv2.setTrackbarPos('Frame', 'IR Recording', i)
    
    else:
        # Update the frame index to the current trackbar position
        i = cv2.getTrackbarPos('Frame', 'IR Recording')

    ###Display the timestamp in Terminal
    print('\rTimeStamp: %.5f' %(ir_ts[i]-ir_ts[0]), end='', flush=True)

    timestep=max(20,int(1000*(ir_ts[i]-ir_ts[i-1])))
    # Wait for a specific time (in milliseconds) before displaying the next frame
    if cv2.waitKey(timestep) & 0xFF == ord('q'):
        break

# Close the window after the loop is completed
cv2.destroyAllWindows()