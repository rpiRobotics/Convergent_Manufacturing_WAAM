from copy import deepcopy
from pathlib import Path
import pickle
import sys
sys.path.append('../scan/scan_tools/')
sys.path.append('../scan/scan_plan/')
sys.path.append('../scan/scan_process/')
sys.path.append('../mocap/')
from motoman_def import *
from scan_utils import *
from scan_continuous import *

from scanProcess import *
from PH_interp import *
from robotics_utils import *
from weldCorrectionStrategy import *
from weld_dh2v import *
import open3d as o3d

from general_robotics_toolbox import *
import matplotlib.pyplot as plt
import time
import datetime
import numpy as np
import glob
import yaml
from math import ceil,floor

R1_ph_dataset_date='0926'
R2_ph_dataset_date='0926'
S1_ph_dataset_date='0926'

zero_config=np.zeros(6)
# 0. robots.
config_dir='../config/'
R1_marker_dir=config_dir+'MA2010_marker_config/'
weldgun_marker_dir=config_dir+'weldgun_marker_config/'
R2_marker_dir=config_dir+'MA1440_marker_config/'
mti_marker_dir=config_dir+'mti_marker_config/'
S1_marker_dir=config_dir+'D500B_marker_config/'
S1_tcp_marker_dir=config_dir+'positioner_tcp_marker_config/'
robot_weld=robot_obj('MA2010_A0',def_path=config_dir+'MA2010_A0_robot_default_config.yml',d=15,tool_file_path=config_dir+'torch.csv',\
	pulse2deg_file_path=config_dir+'MA2010_A0_pulse2deg_real.csv',\
    base_marker_config_file=R1_marker_dir+'MA2010_'+R1_ph_dataset_date+'_marker_config.yaml',tool_marker_config_file=weldgun_marker_dir+'weldgun_'+R1_ph_dataset_date+'_marker_config.yaml')
robot_scan=robot_obj('MA1440_A0',def_path=config_dir+'MA1440_A0_robot_default_config.yml',tool_file_path=config_dir+'mti.csv',\
	base_transformation_file=config_dir+'MA1440_pose.csv',pulse2deg_file_path=config_dir+'MA1440_A0_pulse2deg_real.csv',\
    base_marker_config_file=R2_marker_dir+'MA1440_'+R2_ph_dataset_date+'_marker_config.yaml',tool_marker_config_file=mti_marker_dir+'mti_'+R2_ph_dataset_date+'_marker_config.yaml')

positioner=positioner_obj('D500B',def_path=config_dir+'D500B_robot_default_config.yml',tool_file_path=config_dir+'positioner_tcp.csv',\
    base_transformation_file=config_dir+'D500B_pose.csv',pulse2deg_file_path=config_dir+'D500B_pulse2deg_real.csv',\
    base_marker_config_file=S1_marker_dir+'D500B_'+S1_ph_dataset_date+'_marker_config.yaml',tool_marker_config_file=S1_tcp_marker_dir+'positioner_tcp_marker_config.yaml')

#### change base H to calibrated ones ####
robot_scan_base = robot_weld.T_base_basemarker.inv()*robot_scan.T_base_basemarker
robot_scan.base_H = H_from_RT(robot_scan_base.R,robot_scan_base.p)
positioner_base = robot_weld.T_base_basemarker.inv()*positioner.T_base_basemarker
positioner.base_H = H_from_RT(positioner_base.R,positioner_base.p)
T_to_base = Transform(np.eye(3),[0,0,-380])
positioner.base_H = np.matmul(positioner.base_H,H_from_RT(T_to_base.R,T_to_base.p))

ph_param_r1=None
ph_param_r2=None
#### load S1 kinematic model

regen_pcd = False
dataset='blade0.1/'
sliced_alg='auto_slice/'
curve_data_dir = '../data/'+dataset+sliced_alg
# data_dir=curve_data_dir+'weld_scan_baseline_2023_10_09_16_01_52'+'/'
data_dir=curve_data_dir+'weld_scan_correction_2023_10_10_16_56_32'+'/'

#### welding spec, goal
with open(curve_data_dir+'slicing.yml', 'r') as file:
    slicing_meta = yaml.safe_load(file)
line_resolution = slicing_meta['line_resolution']
total_layer = slicing_meta['num_layers']
total_baselayer = slicing_meta['num_baselayers']

all_layer_dir=glob.glob(data_dir+'layer_*_0')
total_print_layer = len(all_layer_dir)
total_count=total_print_layer

layer_num = []
for layer_count in range(0,total_count):
    # get printed layer number
    layer=all_layer_dir[layer_count].split('/')
    layer=layer[-1]
    layer=layer.split('\\')
    layer=layer[-1]
    layer=layer.split('_')
    layer=int(layer[1])
    layer_num.append(layer)
layer_num = np.sort(layer_num)

last_curve_relative = []
last_curve_height = []
all_pcd=o3d.geometry.PointCloud()
viz_obj=[]

ipm_mode=100
nominal_v = 5
des_dh = v2dh_loglog(nominal_v,mode=ipm_mode)

# Transz0_H=None
Transz0_H=np.array([[ 9.99977850e-01, -4.63363649e-05, -6.65562283e-03,  5.00198327e-03],
 [-4.63363649e-05,  9.99903067e-01, -1.39231465e-02,  1.04638361e-02],
 [ 6.65562283e-03,  1.39231465e-02,  9.99880917e-01, -7.51452982e-01],
 [ 0.00000000e+00,  0.00000000e+00,  0.00000000e+00,  1.00000000e+00]])

dh_std=[]
dh_norm=[]
dh_rmse=[]
all_layer_dh=[]
all_layer_deviation=[]
all_layer_ldot=[]
for layer_count in range(0,total_count):
    baselayer=False
    # if layer_count!= 0 and layer_count<=total_baselayer:
    #     baselayer=True
    
    # get printed layer number
    layer=int(layer_num[layer_count])
    
    print("Layer:",layer)
        
    layer_data_dir=data_dir+'layer_'+str(layer)+'_'
    
    num_sections = len(glob.glob(layer_data_dir+'*'))
    pcd_layer=o3d.geometry.PointCloud()
    
    layer_curve_relative=[]
    layer_curve_dh=[]
    layer_ldot=[]
    for x in range(num_sections):
        layer_sec_data_dir=layer_data_dir+str(x)+'/'
        out_scan_dir = layer_sec_data_dir+'scans/'
        print(out_scan_dir)
        
        if layer<0:
            read_layer=0
        else:
            read_layer=layer
        if not baselayer:
            curve_sliced_relative=np.loadtxt(curve_data_dir+'curve_sliced_relative/slice'+str(read_layer)+'_'+str(x)+'.csv',delimiter=',')
            curve_sliced_js=np.loadtxt(curve_data_dir+'curve_sliced_js/MA2010_js'+str(read_layer)+'_'+str(x)+'.csv',delimiter=',').reshape((-1,6))
            positioner_js=np.loadtxt(curve_data_dir+'curve_sliced_js/D500B_js'+str(read_layer)+'_'+str(x)+'.csv',delimiter=',')
        else:
            curve_sliced_relative=np.loadtxt(curve_data_dir+'curve_sliced_relative/baselayer'+str(read_layer)+'_'+str(x)+'.csv',delimiter=',')
            curve_sliced_js=np.loadtxt(curve_data_dir+'curve_sliced_js/MA2010_base_js'+str(read_layer)+'_'+str(x)+'.csv',delimiter=',').reshape((-1,6))
            positioner_js=np.loadtxt(curve_data_dir+'curve_sliced_js/D500B_base_js'+str(read_layer)+'_'+str(x)+'.csv',delimiter=',')
        
        rob_js_plan = np.hstack((curve_sliced_js,positioner_js))
        
        with open(out_scan_dir+'mti_scans.pickle', 'rb') as file:
            mti_recording=pickle.load(file)
        q_out_exe=np.loadtxt(out_scan_dir+'scan_js_exe.csv',delimiter=',')
        robot_stamps=np.loadtxt(out_scan_dir+'scan_robot_stamps.csv',delimiter=',')

        scan_process = ScanProcess(robot_scan,positioner)
        if regen_pcd:
            #### scanning process: processing point cloud and get h
            crop_extend=15
            crop_min=tuple(np.min(curve_sliced_relative[:,:3],axis=0)-crop_extend)
            crop_max=tuple(np.max(curve_sliced_relative[:,:3],axis=0)+crop_extend)
            pcd = scan_process.pcd_register_mti(mti_recording,q_out_exe,robot_stamps,use_calib=True,ph_param=ph_param_r2)
            # pcd = scan_process.pcd_register_mti(mti_recording,q_out_exe,robot_stamps,use_calib=False)
            # visualize_pcd([pcd])
            cluser_minp = 325
            while True:
                pcd_new = scan_process.pcd_noise_remove(pcd,nb_neighbors=40,std_ratio=1.5,\
                                                    min_bound=crop_min,max_bound=crop_max,outlier_remove=True,cluster_based_outlier_remove=True,cluster_neighbor=1,min_points=cluser_minp)
                break
            pcd=pcd_new
            pcd,Transz0_H = scan_process.pcd_calib_z(pcd,Transz0_H=Transz0_H)
        else:
            pcd=o3d.io.read_point_cloud(out_scan_dir+'processed_pcd.pcd')
        pcd_layer+=pcd
        
        # dh plot
        if layer!=-1:
            # profile_height = scan_process.pcd2dh(pcd,last_pcd,curve_sliced_relative,robot_weld,rob_js_plan,ph_param=ph_param_r1,drawing=True)
            if layer_count<total_count-8:
                profile_height = scan_process.pcd2dh(pcd,curve_sliced_relative,drawing=False)
            else:
                profile_height = scan_process.pcd2dh(pcd,curve_sliced_relative,drawing=False)
            
            # if len(layer_curve_dh)!=0:
            #     profile_height[:,0]+=layer_curve_dh[-1][0]
            ## correct the lambda based on previous
            start_lambda=0
            if layer>0:
                closest_id = np.argmin(np.linalg.norm(last_curve_relative[:,:3]-curve_sliced_relative[0,:3],axis=1))
                start_lambda = all_layer_dh[-1][closest_id,0]
                print("Start lambda:",start_lambda)
                profile_height[:,0]+=start_lambda
                
            layer_curve_dh.extend(profile_height)
        layer_curve_relative.extend(curve_sliced_relative)
        
        ## load weld js exe
        weld_js_exe = np.loadtxt(layer_sec_data_dir+'weld_js_exe.csv',delimiter=',')
        weld_stamps = np.loadtxt(layer_sec_data_dir+'weld_robot_stamps.csv',delimiter=',')
        ldot=[0]
        lam=[0]
        last_p=None
        js_id=0
        for js in weld_js_exe:
            R1TCP = robot_weld.fwd(js[:6])
            S1TCP_R1BASE = positioner.fwd(js[-2:],world=True)
            R1TCP_S1TCP = S1TCP_R1BASE.inv()*R1TCP
            if last_p is not None:
                lam.append(lam[-1]+np.linalg.norm(R1TCP_S1TCP.p-last_p))
                ldot.append(np.linalg.norm(R1TCP_S1TCP.p-last_p)/(weld_stamps[js_id]-weld_stamps[js_id-1]))
                # ldot.append(np.linalg.norm(R1TCP_S1TCP.p-last_p)/0.004)
            last_p=deepcopy(R1TCP_S1TCP.p)
            js_id+=1
        lam=np.array(lam)
        ldot=np.array(ldot)
        ldot_smooth = moving_average(ldot, n=21, padding=True)
        weld_start_id = np.argmin(ldot_smooth[100:250])+100
        ldot=ldot[weld_start_id:]
        ldot_smooth=ldot_smooth[weld_start_id:]
        lam=lam[weld_start_id:]
        lam=lam-lam[0]+start_lambda
        
        if layer_count%2==1:
            lam=lam[::-1]
            lam=lam[0]+lam[-1]-lam
            ldot=ldot[::-1]
            ldot_smooth=ldot_smooth[::-1]
        
        # plt.scatter(lam,ldot)
        # plt.plot(lam,ldot_smooth,c='tab:orange')
        # plt.show()
        ldot_lam = np.array([lam,ldot_smooth]).T
        layer_ldot.extend(ldot_lam)
    last_pcd=pcd_layer
    
    all_pcd=all_pcd+last_pcd
    
    layer_curve_relative=np.array(layer_curve_relative)
    last_curve_relative=deepcopy(layer_curve_relative)

    layer_curve_dh=np.array(layer_curve_dh)
    all_layer_dh.append(layer_curve_dh)
    layer_curve_deviation = np.array(layer_curve_dh)
    layer_curve_deviation[:,1] = des_dh-layer_curve_deviation[:,1]
    all_layer_deviation.append(layer_curve_deviation)
    layer_ldot=np.array(layer_ldot)
    all_layer_ldot.append(layer_ldot)
    
    if layer!=-1:
        dh_std.append(np.std(layer_curve_dh[:,1]))
        dh_norm.append(np.linalg.norm(layer_curve_deviation[:,1]))
        rmse = np.sqrt(np.sum(layer_curve_deviation[:,1]**2)/len(layer_curve_deviation[:,1]))
        dh_rmse.append(rmse)

viz_obj.append(all_pcd)
visualize_pcd(viz_obj)
# save pcd 
o3d.io.write_point_cloud(data_dir+'pcd_blade.pcd',all_pcd)

draw_l_count=0
for lh in all_layer_dh:
    draw_color='tab:blue' if draw_l_count%2==0 else 'tab:orange'
    plt.scatter(lh[:,0],lh[:,1]+layer_num[draw_l_count]/10.,c=draw_color)
    draw_l_count+=1
plt.xlabel("Path length (lambda) (mm)",fontsize=20)
plt.ylabel("Height (mm)",fontsize=20)
plt.xticks(fontsize=20)
plt.yticks(fontsize=20)
plt.title("Layer Height",fontsize=24)
plt.show()

draw_l_count=0
for ldot in all_layer_ldot:
    draw_color='tab:blue' if draw_l_count%2==0 else 'tab:orange'
    plt.plot(ldot[:,0],ldot[:,1]+draw_l_count*(nominal_v*2),c=draw_color)
    draw_l_count+=1
plt.xlabel("Path length (lambda) (mm)",fontsize=16)
plt.ylabel("Layer #",fontsize=16)
plt.xticks(fontsize=16)
plt.yticks(np.arange(draw_l_count)*(nominal_v*2),np.arange(1,draw_l_count+1),fontsize=16)
plt.title("Layer Ldot vs lambda",fontsize=20)
plt.show()

# save std data
np.save(data_dir+'height_std.npy',dh_std)
np.save(data_dir+'height_error_norm.npy',dh_norm)
np.save(data_dir+'height_rmse.npy',dh_rmse)

