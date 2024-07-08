import cv2,copy
from tqdm import tqdm
import pickle, sys, time
import numpy as np
import matplotlib.pyplot as plt
from pandas import read_csv
sys.path.append('../../toolbox/')
from flir_toolbox import *
from robot_def import *
from ultralytics import YOLO


def center_of_window_below_bbox(centroid,ir_pixel_window_size, num_pixel_below_centroid=0):

    center_x = centroid[0]
    center_y = centroid[1]+num_pixel_below_centroid+ir_pixel_window_size//2

    return center_x, center_y

#load model
yolo_model = YOLO("../tracking/yolov8/torch.pt")


# Load the IR recording data from the pickle file
data_dir='../../../recorded_data/ER316L/cylinderspiral_100ipm_v10/'
config_dir='../../config/'
with open(data_dir+'/ir_recording.pickle', 'rb') as file:
    ir_recording = pickle.load(file)
ir_ts=np.loadtxt(data_dir+'/ir_stamps.csv', delimiter=',')
joint_angle=np.loadtxt(data_dir+'weld_js_exe.csv',delimiter=',')


frame_start=12000
ir_pixel_window_size=7

pixel_value_all=[]
ir_ts_processed=[]
for i in tqdm(range(frame_start, len(ir_recording))):
    ir_image = np.rot90(ir_recording[i], k=-1)
    centroid, bbox=flame_detection_yolo(ir_image,yolo_model,percentage_threshold=0.8)    #cylinder spiral only
    if centroid is not None:
        #find average pixel value 
        pixel_coord=center_of_window_below_bbox(centroid,ir_pixel_window_size)
        pixel_value_all.append(get_pixel_value(ir_image,pixel_coord,ir_pixel_window_size))
        ir_ts_processed.append(ir_ts[i])




plt.title('Pixel Value vs Time ')
plt.plot(ir_ts_processed, pixel_value_all)
plt.xlabel('Time (s)')
plt.ylabel('Pixel Value')
plt.show()