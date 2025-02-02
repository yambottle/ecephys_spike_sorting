import os
import shutil
import subprocess
import numpy as np

from helpers import SpikeGLX_utils
from helpers import log_from_json
from create_input_json import createInputJson

# script to run CatGT, KS2, postprocessing and TPrime on data collected using
# SpikeGLX. The construction of the paths assumes data was saved with
# "Folder per probe" selected (probes stored in separate folders) AND
# that CatGT is run with the -out_prb_fld option

# -----------
# Input data
# -----------
# Name for log file for this pipeline run. Log file will be saved in the
# output destination directory catGT_dest
logName = 'dl56_20181126_log.csv'

# Raw data directory = npx_directory, all runs to be processed are in
# subfolders of this folder
npx_directory = r'D:\ecephys_fork\test_data\3A_DL'

# run_specs = name, gate, trigger and probes to process
# Each run_spec is a list:
#   (string) animal name = undecorated run name , e.g. 'dl56',
#   (string) date of recording, as yyyymmdd, eg '20181126'
#   (string) gate index, as a string (e.g. '0')
#   (string) triggers to process/concatenate, as a string e.g. '0,400', '0,0', 
#           can replace first limit with 'start', last with 'end'; 'start,end'
#           will concatenate all trials in the probe folder
#   (list of strings) computer/ probe labels to process, as a list, e.g. ['ww2','ww4']
#   (list of ints) SY channel for each run -- if no SY channel, or not extracting that data, enter None
#
#   The assumed file structure for input is:
#   /probe(computer) label/date/animal name/*.bin files
#   Note that the both the folder name and run name = animal name
#   Does not use SpikeGLX generated run folders

run_specs = [
					['dl56', '20181126', '0', 'start,end', ['ww2','ww4'], [384,384]]
]



# ------------------
# Output destination
# ------------------
# Set to an existing directory; all output will be written here, in
# subfolders named animal name_date
catGT_dest_parent = r'D:\ecephys_fork\test_data\3A_DL\DL56'

# ------------
# CatGT params
# ------------
run_CatGT = True  # set to False to sort/process previously processed data.
# catGT streams to process, e.g. just '-ap' for ap band only, '-ap -ni' for
# ap plus ni aux inputs
catGT_stream_string = '-prb_3A -ap -no_run_fld -t_miss_ok'

# CatGT command string includes all instructions for catGT operations
# see CatGT readme for details
# 3A specific details:
#   -no automatically generated run folders. Assume user has grouped data from the probes
#   -into one folder, named in the run_spec
#   -no probe folders -- each call to catGT processes one probes data.
#   - the extraction parameters (bit, length in msec) are assumed to be the same for all probes
#   - the correct channel for the extraction is specfied in run_spec[4]
catGT_cmd_string = '-aphipass=300 -aplopass=9000 -gbldmx -gfix=0,0.10,0.02'

# for each desired estraction from the SY channel, specify:
# bit, span in msec, and tolerance in ms, or -1 to use default
# tolerance of 20% of span
# the extraction strings for catGT will be built for each probe
sy_ex_param_list = list()
sy_ex_param_list.append([0, 0, -1])
sy_ex_param_list.append([1, 50, -1])
sy_ex_param_list.append([1, 10, -1])
sy_ex_param_list.append([1, 1200, 0.2])

# ----------------------
# psth_events parameters
# ----------------------
# extract param string for psth events -- copy the CatGT params used to extract
# events that should be exported with the phy output for PSTH plots
# With 3A, it is assumed that the same extraction parameters will be used for
# all probes, and the index is specfied here
# If not using, remove psth_events from the list of modules
event_ex_param_index = 1

# -----------------
# TPrime parameters
# -----------------
runTPrime = True   # set to False if not using TPrime
sync_period = 12.0   # true for SYNC wave, in 3A using the trial TTL signal
sync_param = [0, 0, -1] # SYNC bit and msec duration of SYNC signal

# ---------------
# Modules List
# ---------------
# List of modules to run per probe; 
# CatGT is handled separated; TPrime is called once for each run.
modules = [
			'kilosort_helper',
            'kilosort_postprocessing',
            'noise_templates',
            #'psth_events',
            'mean_waveforms',
            'quality_metrics'
			]

json_directory = r'D:\ecephys_fork\json_files'


# delete the existing CatGT.log
try:
    os.remove('CatGT.log')
except OSError:
    pass

# delete existing Tprime.log
try:
    os.remove('Tprime.log')
except OSError:
    pass

# delete existing C_waves.log
try:
    os.remove('C_Waves.log')
except OSError:
    pass

# delete any existing log with the current name
logFullPath = os.path.join(catGT_dest_parent, logName)
try:
    os.remove(logFullPath)
except OSError:
    pass

# create the log file, write header
log_from_json.writeHeader(logFullPath)


for spec in run_specs:

    session_id = spec[0] + '_' + spec[1] + '_g' + spec[2]

    # if the directory animal name_date does not yet exist, create it
    catGT_dest = os.path.join(catGT_dest_parent, session_id)
    if not os.path.exists(catGT_dest):
        os.mkdir(catGT_dest)

    # probe list == probe label list for 3A
    prb_list = spec[4]

    # create space for gfix_edits read from catGT log
    gfix_edits = np.zeros(len(prb_list), dtype='float64')

    # inputs for tPrime
    fromStream_list = list()

    for i, prb in enumerate(prb_list):

        #   Path to folder containing bindaries.
        #   The assumed file structure for input is:
        #   /probe(computer) label/animal name/date/*.bin files
        runFolder = os.path.join(npx_directory, prb, spec[0], spec[1])
        # name of run in input data; note that this run name is not unique
        # but repeated for different dates
        runName = spec[0]

        # build parameter strings for catGT edge extractions for this probe
        currSY = spec[5][i]
        
        # build the "final" name for the catGT output folder
        # CatGT output will intially go into a folder named for the input;
        # after running rename to this name
        final_catGT_name = 'catgt_' + spec[0] + '_' + spec[1] + prb + '_g' + spec[2]
        final_catGT_dest = os.path.join( catGT_dest, final_catGT_name)
        print('final_catGT_dest: ', final_catGT_dest)

        if currSY is not None:
            ex_param_str = ''
            for exparam in sy_ex_param_list:
                if exparam[2] == -1:
                    # use default tolerance
                    currStr = ('SY=0,{0:d},{1:d},{2:d}'.format(currSY, exparam[0], exparam[1]))
                else:
                    currStr = ('SY=0,{0:d},{1:d},{2:d},{3:.1f}'.format(currSY, exparam[0], exparam[1], exparam[2]))
                ex_param_str = ex_param_str + ' -' + currStr
                if exparam == sync_param:
                    # for Tprime, build path to extracted edges  
                    currNameStr = ('SY_{0:d}_{1:d}_{2:d}'.format(currSY, exparam[0], exparam[1]))
                    sy_name = runName + '_g' + spec[2] + '_tcat.imec.' + currNameStr + '.txt'
                    sy_path = os.path.join(catGT_dest, final_catGT_dest, sy_name)
                    if i == 0:
                        # this will be the toStream
                        toStream = sy_path
                        print('toStream path: ', toStream)
                    else:
                        #append to list of fromStream paths
                        fromStream_list.append(sy_path)
                        print('fromStream path: ', fromStream_list[len(fromStream_list)-1])
                        
            probe_catGT_cmd_string = catGT_cmd_string + ' ' + ex_param_str            
       
        # build parameter string for PSTH events     
        if 'psth_events' in modules:
            exparam = sy_ex_param_list[event_ex_param_index]
            event_ex_param_str = ('SY=0,{0:d},{1:d},{2:d}'.format(currSY, exparam[0], exparam[1]))
        else:
            event_ex_param_str = 'SY=0,384,1,50'  # just default filler
            
        

        # Run CatGT
        input_json = os.path.join(json_directory, session_id + '-input.json')
        output_json = os.path.join(json_directory, session_id + '-output.json')
        print('Creating json file for preprocessing')
        print(runFolder)
        # In this case, the run folder and probe folder are the same;
        # parse trigger string using this folder to interpret 'start' and 'end'
        first_trig, last_trig = SpikeGLX_utils.ParseTrigStr(spec[3], runFolder)      
        trigger_str = repr(first_trig) + ',' + repr(last_trig)
        
        info = createInputJson(input_json, npx_directory=runFolder, 
    	                                   continuous_file = None,
                                           spikeGLX_data = 'True',
    									   kilosort_output_directory=catGT_dest,
                                           catGT_run_name = runName,
                                           gate_string = spec[2],
                                           trigger_string = trigger_str,
                                           probe_string = '',
                                           catGT_stream_string = catGT_stream_string,
                                           catGT_cmd_string = probe_catGT_cmd_string,
                                           extracted_data_directory = catGT_dest
                                           )
    
    
    
    
        if run_CatGT:
            
            command = "python -W ignore -m ecephys_spike_sorting.modules." + 'catGT_helper' + " --input_json " + input_json \
    		          + " --output_json " + output_json
            subprocess.check_call(command.split(' '))           
    
            # parse the CatGT log and write results to command line
            # for 3A, there's only one probe, called 0
            gfix_edits = SpikeGLX_utils.ParseCatGTLog( os.getcwd(), runName, spec[2], ['0'] )
            edit_string  = '{:.3f}'.format(gfix_edits[0])
            print(runName + ' gfix edits/sec: ' + edit_string)
            
            # rename output folder a name that includes the date and probe name
            
            orig_catGT_name = 'catgt_' + runName + '_g' + spec[2]
            orig_catGT_out = os.path.join(catGT_dest, orig_catGT_name)
            
            os.rename(orig_catGT_out, final_catGT_dest)
            

             
        # finsihed preprocessing.

        #create json files specific to this probe
        input_json = os.path.join(json_directory, spec[0] + prb + '-input.json')
        
        
        # location of the binary after renaming 
        data_directory = final_catGT_dest
        # fileName, built from the input run name
        fileName = runName + '_g' + spec[2] + '_tcat.imec.ap.bin'
        continuous_file = os.path.join(data_directory, fileName)
 
        outputName = 'imec_' + prb + '_ks2'

        # kilosort_postprocessing and noise_templates moduules alter the files
        # that are input to phy. If using these modules, keep a copy of the
        # original phy output
        if ('kilosort_postprocessing' in modules) or('noise_templates' in modules):
            ks_make_copy = True
        else:
            ks_make_copy = False

        kilosort_output_dir = os.path.join(data_directory, outputName)

        print(data_directory)
        print(continuous_file)

        info = createInputJson(input_json, npx_directory=npx_directory, 
	                                   continuous_file = continuous_file,
                                       spikeGLX_data = True,
									   kilosort_output_directory=kilosort_output_dir,
                                       ks_make_copy = ks_make_copy,
                                       noise_template_use_rf = False,
                                       catGT_run_name = session_id,
                                       gate_string = spec[1],
                                       trigger_string = trigger_str,
                                       probe_string = '',
                                       catGT_stream_string = catGT_stream_string,
                                       catGT_cmd_string = probe_catGT_cmd_string,
                                       catGT_gfix_edits = gfix_edits[0],
                                       extracted_data_directory = catGT_dest,
                                       event_ex_param_str = event_ex_param_str
                                       )   

        # copy json file to data directory as record of the input parameters (and gfix edit rates)  
        shutil.copy(input_json, os.path.join(data_directory, session_id + '-input.json'))
        
        for module in modules:
            output_json = os.path.join(json_directory, session_id + '-' + module + '-output.json')  
            command = "python -W ignore -m ecephys_spike_sorting.modules." + module + " --input_json " + input_json \
		          + " --output_json " + output_json
            subprocess.check_call(command.split(' '))
            
        log_from_json.addEntry(modules, json_directory, session_id, logFullPath)
                   
    if runTPrime:
        # after loop over probes, run TPrime to create files of 
        # event times -- edges detected in auxialliary files and spike times 
        # from each probe -- all aligned to a reference stream.
    
        # create json files for calling TPrime
        session_id = spec[0] + '_TPrime'
        input_json = os.path.join(json_directory, session_id + '-input.json')
        output_json = os.path.join(json_directory, session_id + '-output.json')
        
        info = createInputJson(input_json, npx_directory=npx_directory, 
    	                                   continuous_file = continuous_file,
                                           spikeGLX_data = True,
    									   kilosort_output_directory=kilosort_output_dir,
                                           ks_make_copy = ks_make_copy,
                                           noise_template_use_rf = False,
                                           catGT_run_name = spec[0],
                                           gate_string = spec[1],
                                           trigger_string = trigger_str,
                                           probe_string = '',
                                           catGT_stream_string = catGT_stream_string,
                                           catGT_cmd_string = catGT_cmd_string,
                                           catGT_gfix_edits = gfix_edits[0],
                                           extracted_data_directory = catGT_dest,
                                           event_ex_param_str = event_ex_param_str,
                                           sync_period = sync_period,
                                           toStream_sync_params = '',
                                           niStream_sync_params = '',
                                           toStream_path_3A = toStream,
                                           fromStream_list_3A = fromStream_list
                                           ) 
        
        command = "python -W ignore -m ecephys_spike_sorting.modules." + 'tPrime_helper' + " --input_json " + input_json \
    		          + " --output_json " + output_json
        subprocess.check_call(command.split(' '))  
    