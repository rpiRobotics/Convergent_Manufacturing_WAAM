import sys, time
sys.path.append('../toolbox/')
from robot_def import *
from WeldSend import *
from dx200_motion_program_exec_client import *
from RobotRaconteur.Client import *

image_consts = None

def main():
	##############################################################FLIR####################################################################
	
	url='rr+tcp://192.168.55.15:60827/?service=camera'

	c1=RRN.ConnectService(url)
	c1.setf_param("focus_pos", RR.VarValue(int(1900),"int32"))
	c1.setf_param("object_distance", RR.VarValue(0.3,"double"))
	c1.setf_param("reflected_temperature", RR.VarValue(291.15,"double"))
	c1.setf_param("atmospheric_temperature", RR.VarValue(293.15,"double"))
	c1.setf_param("relative_humidity", RR.VarValue(50,"double"))
	c1.setf_param("ext_optics_temperature", RR.VarValue(293.15,"double"))
	c1.setf_param("ext_optics_transmission", RR.VarValue(0.99,"double"))

	c1.setf_param("current_case", RR.VarValue(2,"int32"))
	# c1.setf_param("ir_format", RR.VarValue("temperature_linear_100mK","string"))
	c1.setf_param("ir_format", RR.VarValue("radiometric","string"))

	c1.setf_param("object_emissivity", RR.VarValue(0.9,"double"))
	c1.setf_param("scale_limit_low", RR.VarValue(293.15,"double"))
	c1.setf_param("scale_limit_upper", RR.VarValue(5000,"double"))

	global image_consts, ir_ts_all
	image_consts = RRN.GetConstants('com.robotraconteur.image', c1)
	ir_ts_all = []
	p=c1.frame_stream.Connect(-1)

	#Set the callback for when a new pipe packet is received to the
	#new_frame function
	p.PacketReceivedEvent+=new_frame
	try:
		c1.start_streaming()
	except: pass

	##############################################################Robot####################################################################
	###robot kinematics def
	robot=robot_obj('MA2010_A0',def_path='../config/MA2010_A0_robot_default_config.yml',tool_file_path='../config/torch.csv',\
		pulse2deg_file_path='../config/MA2010_A0_pulse2deg_real.csv',d=15)
	robot2=robot_obj('MA1440_A0',def_path='../config/MA1440_A0_robot_default_config.yml',tool_file_path='../config/flir.csv',\
		pulse2deg_file_path='../config/MA1440_A0_pulse2deg_real.csv',base_transformation_file='../config/MA1440_pose.csv')
	positioner=positioner_obj('D500B',def_path='../config/D500B_robot_default_config.yml',tool_file_path='../config/positioner_tcp.csv',\
		pulse2deg_file_path='../config/D500B_pulse2deg_real.csv',base_transformation_file='../config/D500B_pose_mocap.csv')

	###define start pose for 3 robtos
	measure_distance=400
	H2010_1440=H_inv(robot2.base_H)
	q_positioner_home=np.array([15.*np.pi/180.,0])
	p_positioner_home=positioner.fwd(q_positioner_home,world=True).p
	p_robot2_proj=p_positioner_home+np.array([0,0,500])
	p2_in_base_frame=np.dot(H2010_1440[:3,:3],p_robot2_proj)+H2010_1440[:3,3]
	v_z=H2010_1440[:3,:3]@np.array([0,-0.96592582628,-0.2588190451]) ###pointing toward positioner's X with 15deg tiltd angle looking down
	v_y=VectorPlaneProjection(np.array([-1,0,0]),v_z)	###FLIR's Y pointing toward 1440's -X in 1440's base frame, projected on v_z's plane
	v_x=np.cross(v_y,v_z)
	p2_in_base_frame=p2_in_base_frame-measure_distance*v_z			###back project measure_distance-mm away from torch
	R2=np.vstack((v_x,v_y,v_z)).T
	q2=robot2.inv(p2_in_base_frame,R2,last_joints=np.zeros(6))[0]

	###jog to start point
	client=MotionProgramExecClient()
	ws=WeldSend(client)
	ws.jog_dual(robot2,positioner,q_positioner_home,q2,v=1)


	#################################################################robot 1 welding####################################################################
	R=np.array([[-0.7071, 0.7071, -0.    ],
				[ 0.7071, 0.7071,  0.    ],
				[0.,      0.,     -1.    ]])
	p_start=np.array([1630,-840,-260])
	p_end=np.array([1630,-780,-260])
	q_seed=np.radians([-35.4291,56.6333,40.5194,4.5177,-52.2505,-11.6546])


	base_feedrate=200
	feedrate=70
	base_layer_height=2
	layer_height=1.0
	q_all=[]
	v_all=[]
	job_offset=100
	cond_all=[]
	primitives=[]

	####################################Base Layer ####################################
	for i in range(0,2):
		if i%2==0:
			p1=p_start+np.array([0,0,i*base_layer_height])
			p2=p_end+np.array([0,0,i*base_layer_height])
		else:
			p1=p_end+np.array([0,0,i*base_layer_height])
			p2=p_start+np.array([0,0,i*base_layer_height])

		
		q_init=robot.inv(p1,R,q_seed)[0]
		q_end=robot.inv(p2,R,q_seed)[0]

		# p_mid1=p1+5*(p2-p1)/np.linalg.norm(p2-p1)
		# p_mid2=p2-5*(p2-p1)/np.linalg.norm(p2-p1)
		# q_mid1=robot.inv(p_mid1,R,q_seed)[0]
		# q_mid2=robot.inv(p_mid2,R,q_seed)[0]

		q_all.extend([q_init,q_end])
		v_all.extend([1,10])
		primitives.extend(['movej','movel'])
		cond_all.extend([0,base_feedrate/10+job_offset])


	####################################Normal Layer ####################################

	for i in range(2,3):
		if i%2==0:
			p1=p_start+np.array([0,0,2*base_layer_height+i*layer_height])
			p2=p_end+np.array([0,0,2*base_layer_height+i*layer_height])
		else:
			p1=p_end+np.array([0,0,2*base_layer_height+i*layer_height])
			p2=p_start+np.array([0,0,2*base_layer_height+i*layer_height])

		q_init=robot.inv(p1,R,q_seed)[0]
		q_end=robot.inv(p2,R,q_seed)[0]
		q_all.extend([q_init,q_end])
		v_all.extend([1,15])
		primitives.extend(['movel'])
		cond_all.extend([feedrate/10+job_offset])


	ws.weld_segment_single(primitives,robot,q_all,v_all,cond_all,arc=False,wait=0.,blocking=False)
	##############################################################Log Joint Data####################################################################
	js_recording=[]
	start_time=time.time()
	while not(client.state_flag & 0x08 == 0 and time.time()-start_time>1.):
		res, fb_data = client.fb.try_receive_state_sync(client.controller_info, 0.001)
		if res:
			with client._lock:
				client.joint_angle=np.hstack((fb_data.group_state[0].feedback_position,fb_data.group_state[1].feedback_position,fb_data.group_state[2].feedback_position))
				client.state_flag=fb_data.controller_flags
				js_recording.append(np.array([time.time()]+client.joint_angle.tolist()+[fb_data.job_state[0][1],fb_data.job_state[0][2]]))


current_mat=None

##############################################################FLIR Callback####################################################################
def new_frame(pipe_ep):
    global current_mat, ir_ts_all

    #Loop to get the newest frame
    while (pipe_ep.Available > 0):
        #Receive the packet
        rr_img=pipe_ep.ReceivePacket()
        if rr_img.image_info.encoding == image_consts["ImageEncoding"]["mono8"]:
            # Simple uint8 image
            mat = rr_img.data.reshape([rr_img.image_info.height, rr_img.image_info.width], order='C')
        elif rr_img.image_info.encoding == image_consts["ImageEncoding"]["mono16"]:
            data_u16 = np.array(rr_img.data.view(np.uint16))
            mat = data_u16.reshape([rr_img.image_info.height, rr_img.image_info.width], order='C')
        
        ir_format = rr_img.image_info.extended["ir_format"].data

        if ir_format == "temperature_linear_10mK":
            display_mat = (mat * 0.01) - 273.15    
        elif ir_format == "temperature_linear_100mK":
            display_mat = (mat * 0.1) - 273.15    
        else:
            display_mat = mat

        #Convert the packet to an image and set the global variable
        ir_ts_all.append(time.time())
        current_mat = display_mat
        