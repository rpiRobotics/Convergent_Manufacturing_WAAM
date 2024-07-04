import sys, time, pickle, os, glob
sys.path.append('../../toolbox/')
from robot_def import *
from lambda_calc import *
from WeldSend import *
sys.path.append('../../sensor_fusion/')
from dx200_motion_program_exec_client import *
from RobotRaconteur.Client import *
from weldRRSensor import *
from traj_manipulation import *


def main():

	dataset='cylinder/'
	sliced_alg='dense_slice/'
	data_dir='../../data/'+dataset+sliced_alg
	with open(data_dir+'slicing.yml', 'r') as file:
		slicing_meta = yaml.safe_load(file)

	waypoint_distance=5 	###waypoint separation

	##############################################################SENSORS####################################################################
	# weld state logging
	# weld_ser = RRN.SubscribeService('rr+tcp://192.168.55.10:60823?service=welder')
	cam_ser=RRN.ConnectService('rr+tcp://localhost:60827/?service=camera')
	# mic_ser = RRN.ConnectService('rr+tcp://192.168.55.20:60828?service=microphone')
	## RR sensor objects
	rr_sensors = WeldRRSensor(weld_service=None,cam_service=cam_ser,microphone_service=None)

	##############################################################Robot####################################################################
	###robot kinematics def
	config_dir='../../config/'
	robot=robot_obj('MA2010_A0',def_path=config_dir+'MA2010_A0_robot_default_config.yml',tool_file_path=config_dir+'torch.csv',\
		pulse2deg_file_path=config_dir+'MA2010_A0_pulse2deg_real.csv',d=15)
	robot2=robot_obj('MA1440_A0',def_path=config_dir+'MA1440_A0_robot_default_config.yml',tool_file_path=config_dir+'flir.csv',\
		pulse2deg_file_path=config_dir+'MA1440_A0_pulse2deg_real.csv',base_transformation_file=config_dir+'MA1440_pose.csv')
	positioner=positioner_obj('D500B',def_path=config_dir+'D500B_robot_default_config.yml',tool_file_path=config_dir+'positioner_tcp.csv',\
		pulse2deg_file_path=config_dir+'D500B_pulse2deg_real.csv',base_transformation_file=config_dir+'D500B_pose_mocap.csv')

	###define start pose for 3 robtos
	measure_distance=500
	H2010_1440=H_inv(robot2.base_H)
	q_positioner_home=np.array([-15.*np.pi/180.,np.pi/2])
	# p_positioner_home=positioner.fwd(q_positioner_home,world=True).p
	rob1_js=np.loadtxt(data_dir+'curve_sliced_js/MA2010_js0_0.csv',delimiter=',')
	positioner_js=np.loadtxt(data_dir+'curve_sliced_js/D500B_js0_0.csv',delimiter=',')
	p_positioner_home=np.mean([robot.fwd(rob1_js[0]).p,robot.fwd(rob1_js[-1]).p],axis=0)
	p_robot2_proj=p_positioner_home+np.array([0,0,50])
	p2_in_base_frame=np.dot(H2010_1440[:3,:3],p_robot2_proj)+H2010_1440[:3,3]
	v_z=H2010_1440[:3,:3]@np.array([0,-0.96592582628,-0.2588190451]) ###pointing toward positioner's X with 15deg tiltd angle looking down
	v_y=VectorPlaneProjection(np.array([-1,0,0]),v_z)	###FLIR's Y pointing toward 1440's -X in 1440's base frame, projected on v_z's plane
	v_x=np.cross(v_y,v_z)
	p2_in_base_frame=p2_in_base_frame-measure_distance*v_z			###back project measure_distance-mm away from torch
	R2=np.vstack((v_x,v_y,v_z)).T
	q2=robot2.inv(p2_in_base_frame,R2,last_joints=np.zeros(6))[0]


	#################################################################robot 1 welding params####################################################################
	R=np.array([[-0.7071, 0.7071, -0.    ],
				[ 0.7071, 0.7071,  0.    ],
				[0.,      0.,     -1.    ]])

	
	base_feedrate=300
	volume_per_distance=10
	v_layer=10
	feedrate=volume_per_distance*v_layer
	base_layer_height=3
	v_base=5
	layer_height=0.9
	num_layer=30
	#edge params, 1cm left and right
	feedrate_edge=feedrate
	v_edge=v_layer
	q_all=[]
	v_all=[]
	job_offset=450
	cond_all=[]
	primitives=[]

	nominal_slice_increment=int(layer_height/slicing_meta['line_resolution'])
	base_slice_increment=int(base_layer_height/slicing_meta['line_resolution'])


	q_prev=client.getJointAnglesDB(positioner.pulse2deg)
	num2p=np.round((q_prev-positioner_js[0])/(2*np.pi))
	positioner_js+=num2p*2*np.pi

	###jog to start point
	client=MotionProgramExecClient()
	ws=WeldSend(client)
	ws.jog_dual(robot2,positioner,q2,positioner_js[0],v=1)
	q1_all=[]
	q2_all=[]
	v1_all=[]
	v2_all=[]
	cond_all=[]
	primitives=[]
	arcon_set=False
	
	# #####################################################BASE LAYER##########################################################################################
	# ###PRELOAD ALL SLICES TO SAVE INPROCESS TIME
	# rob1_js_all_slices=[]
	# rob2_js_all_slices=[]
	# positioner_js_all_slices=[]
	# for i in range(0,2*base_slice_increment+1):
	# 	rob1_js_all_slices.append(np.loadtxt(data_dir+'curve_sliced_js/MA2010_js'+str(i)+'_0.csv',delimiter=','))
	# 	rob2_js_all_slices.append(np.loadtxt(data_dir+'curve_sliced_js/MA1440_js'+str(i)+'_0.csv',delimiter=','))
	# 	positioner_js_all_slices.append(np.loadtxt(data_dir+'curve_sliced_js/D500B_js'+str(i)+'_0.csv',delimiter=','))

	# print("PRELOAD FINISHED")

	# num_layer_end=2*base_slice_increment+1
	# for slice_num in range(0,num_layer_end,base_slice_increment):

	# 	####################DETERMINE CURVE ORDER##############################################
	# 	x=0
	# 	rob1_js=copy.deepcopy(rob1_js_all_slices[slice_num])
	# 	rob2_js=copy.deepcopy(rob2_js_all_slices[slice_num])
	# 	positioner_js=copy.deepcopy(positioner_js_all_slices[slice_num])
	# 	curve_sliced_relative=np.loadtxt(data_dir+'curve_sliced_relative/slice'+str(slice_num)+'_'+str(x)+'.csv',delimiter=',')
	# 	if positioner_js.shape==(2,) and rob1_js.shape==(6,):
	# 		continue
		
	# 	###TRJAECTORY WARPING
	# 	if slice_num>0:
	# 		rob1_js_prev=copy.deepcopy(rob1_js_all_slices[slice_num-base_slice_increment])
	# 		rob2_js_prev=copy.deepcopy(rob2_js_all_slices[slice_num-base_slice_increment])
	# 		positioner_js_prev=copy.deepcopy(positioner_js_all_slices[slice_num-base_slice_increment])
	# 		rob1_js,rob2_js,positioner_js=warp_traj(rob1_js,rob2_js,positioner_js,rob1_js_prev,rob2_js_prev,positioner_js_prev,reversed=True)
	# 	if slice_num<num_layer_end-base_slice_increment:
	# 		rob1_js_next=copy.deepcopy(rob1_js_all_slices[slice_num+base_slice_increment])
	# 		rob2_js_next=copy.deepcopy(rob2_js_all_slices[slice_num+base_slice_increment])
	# 		positioner_js_next=copy.deepcopy(positioner_js_all_slices[slice_num+base_slice_increment])
	# 		rob1_js,rob2_js,positioner_js=warp_traj(rob1_js,rob2_js,positioner_js,rob1_js_next,rob2_js_next,positioner_js_next,reversed=False)
				
		
			
	# 	lam_relative=calc_lam_cs(curve_sliced_relative)
	# 	lam1=calc_lam_js(rob1_js,robot)
	# 	lam2=calc_lam_js(positioner_js,positioner)
	# 	num_points_layer=max(2,int(lam_relative[-1]/waypoint_distance))
	# 	breakpoints=np.linspace(0,len(rob1_js)-1,num=num_points_layer).astype(int)
	# 	s1_all,s2_all=calc_individual_speed(v_base,lam1,lam2,lam_relative,breakpoints)
	# 	# s1_all=[0.1]*len(s1_all)
	# 	###find closest %2pi
	# 	num2p=np.round((q_prev-positioner_js[0])/(2*np.pi))
	# 	positioner_js+=num2p*2*np.pi
	# 	###no need for acron/off when spiral, positioner not moving at all
	# 	if not arcon_set:
	# 		arcon_set=True
	# 		q1_all.append(rob1_js[breakpoints[0]])
	# 		q2_all.append(positioner_js[breakpoints[0]])
	# 		v1_all.append(20)
	# 		v2_all.append(5)
	# 		cond_all.append(0)
	# 		primitives.append('movej')
		

	# 	q1_all.extend(rob1_js[breakpoints[1:]].tolist())
	# 	q2_all.extend(positioner_js[breakpoints[1:]].tolist())
	# 	# v1_all.extend(s1_all)
	# 	v1_all.extend([1]*len(s1_all))
	# 	cond_all.extend([int(base_feedrate/10)+job_offset]*(num_points_layer-1))
	# 	primitives.extend(['movel']*(num_points_layer-1))

	# 	for j in range(1,len(breakpoints)):
	# 		positioner_w=v_base/np.linalg.norm(curve_sliced_relative[breakpoints[j]][:2])
	# 		v2_all.append(min(100,100*positioner_w/positioner.joint_vel_limit[1]))
		
	# 	q_prev=copy.deepcopy(positioner_js[-1])

	# ws.weld_segment_dual(primitives,robot,positioner,q1_all,q2_all,v1_all,v2_all,cond_all,arc=True)

	

	#####################################################LAYER Welding##########################################################################################
	###PRELOAD ALL SLICES TO SAVE INPROCESS TIME
	rob1_js_all_slices=[]
	rob2_js_all_slices=[]
	positioner_js_all_slices=[]
	for i in range(2*base_slice_increment+1,slicing_meta['num_layers']):
		rob1_js_all_slices.append(np.loadtxt(data_dir+'curve_sliced_js/MA2010_js'+str(i)+'_0.csv',delimiter=','))
		rob2_js_all_slices.append(np.loadtxt(data_dir+'curve_sliced_js/MA1440_js'+str(i)+'_0.csv',delimiter=','))
		positioner_js_all_slices.append(np.loadtxt(data_dir+'curve_sliced_js/D500B_js'+str(i)+'_0.csv',delimiter=','))

	print("PRELOAD FINISHED")

	num_layer_start=int(2*base_slice_increment+1)
	num_layer_end=slicing_meta['num_layers']
	for slice_num in range(0,num_layer_end,nominal_slice_increment):

		####################DETERMINE CURVE ORDER##############################################
		x=0
		rob1_js=copy.deepcopy(rob1_js_all_slices[slice_num])
		rob2_js=copy.deepcopy(rob2_js_all_slices[slice_num])
		positioner_js=copy.deepcopy(positioner_js_all_slices[slice_num])
		curve_sliced_relative=np.loadtxt(data_dir+'curve_sliced_relative/slice'+str(slice_num)+'_'+str(x)+'.csv',delimiter=',')
		if positioner_js.shape==(2,) and rob1_js.shape==(6,):
			continue
		
		###TRJAECTORY WARPING
		if slice_num>num_layer_start:
			rob1_js_prev=copy.deepcopy(rob1_js_all_slices[slice_num-nominal_slice_increment])
			rob2_js_prev=copy.deepcopy(rob2_js_all_slices[slice_num-nominal_slice_increment])
			positioner_js_prev=copy.deepcopy(positioner_js_all_slices[slice_num-nominal_slice_increment])
			rob1_js,rob2_js,positioner_js=warp_traj(rob1_js,rob2_js,positioner_js,rob1_js_prev,rob2_js_prev,positioner_js_prev,reversed=True)
		if slice_num<num_layer_end-nominal_slice_increment:
			rob1_js_next=copy.deepcopy(rob1_js_all_slices[slice_num+nominal_slice_increment])
			rob2_js_next=copy.deepcopy(rob2_js_all_slices[slice_num+nominal_slice_increment])
			positioner_js_next=copy.deepcopy(positioner_js_all_slices[slice_num+nominal_slice_increment])
			rob1_js,rob2_js,positioner_js=warp_traj(rob1_js,rob2_js,positioner_js,rob1_js_next,rob2_js_next,positioner_js_next,reversed=False)
				
		
			
		lam_relative=calc_lam_cs(curve_sliced_relative)
		lam1=calc_lam_js(rob1_js,robot)
		lam2=calc_lam_js(positioner_js,positioner)
		num_points_layer=max(2,int(lam_relative[-1]/waypoint_distance))
		breakpoints=np.linspace(0,len(rob1_js)-1,num=num_points_layer).astype(int)
		s1_all,s2_all=calc_individual_speed(v_layer,lam1,lam2,lam_relative,breakpoints)
		# s1_all=[0.1]*len(s1_all)
		###find closest %2pi
		num2p=np.round((q_prev-positioner_js[0])/(2*np.pi))
		positioner_js+=num2p*2*np.pi
		###no need for acron/off when spiral, positioner not moving at all
		if not arcon_set:
			arcon_set=True
			q1_all.append(rob1_js[breakpoints[0]])
			q2_all.append(positioner_js[breakpoints[0]])
			v1_all.append(20)
			v2_all.append(5)
			cond_all.append(0)
			primitives.append('movej')
		

		q1_all.extend(rob1_js[breakpoints[1:]].tolist())
		q2_all.extend(positioner_js[breakpoints[1:]].tolist())
		# v1_all.extend(s1_all)
		v1_all.extend([1]*len(s1_all))
		cond_all.extend([int(base_feedrate/10)+job_offset]*(num_points_layer-1))
		primitives.extend(['movel']*(num_points_layer-1))

		for j in range(1,len(breakpoints)):
			positioner_w=v_layer/np.linalg.norm(curve_sliced_relative[breakpoints[j]][:2])
			v2_all.append(min(100,100*positioner_w/positioner.joint_vel_limit[1]))
		
		q_prev=copy.deepcopy(positioner_js[-1])

	ws.weld_segment_dual(primitives,robot,positioner,q1_all,q2_all,v1_all,v2_all,cond_all,arc=arcon_set,blocking=False)
	##############################################################Log Joint Data####################################################################
	js_recording=[]
	rr_sensors.start_all_sensors()
	start_time=time.time()
	while not(client.state_flag & 0x08 == 0 and time.time()-start_time>1.):
		res, fb_data = client.fb.try_receive_state_sync(client.controller_info, 0.001)
		if res:
			with client._lock:
				client.joint_angle=np.hstack((fb_data.group_state[0].feedback_position,fb_data.group_state[1].feedback_position,fb_data.group_state[2].feedback_position))
				client.state_flag=fb_data.controller_flags
				js_recording.append(np.array([time.time()]+[fb_data.job_state[0][1]]+client.joint_angle.tolist()))
	rr_sensors.stop_all_sensors()
	client.servoMH(False) #stop the motor


	recorded_dir='../../../recorded_data/ER316L/cylinderspiral_%iipm_v%i/'%(feedrate,v_layer)
	os.makedirs(recorded_dir,exist_ok=True)
	np.savetxt(recorded_dir+'weld_js_exe.csv',np.array(js_recording),delimiter=',')
	rr_sensors.save_all_sensors(recorded_dir)


if __name__ == '__main__':
	main()