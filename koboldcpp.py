#!/usr/bin/env python3
#-*- coding: utf-8 -*-

# KoboldCpp is an easy-to-use AI text-generation software for GGML models.
# It's a single self contained distributable from Concedo, that builds off llama.cpp,
# and adds a versatile Kobold API endpoint, additional format support,
# backward compatibility, as well as a fancy UI with persistent stories,
# editing tools, save formats, memory, world info, author's note, characters,
# scenarios and everything Kobold and KoboldAI Lite have to offer.

import ctypes
import os, math, re
import argparse
import platform
import base64
import json, sys, http.server, time, asyncio, socket, threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

# constants
sampler_order_max = 7
tensor_split_max = 16
images_max = 4
bias_min_value = -100.0
bias_max_value = 100.0
logprobs_max = 5
default_draft_amount = 8

# abuse prevention
stop_token_max = 256
ban_token_max = 512
logit_bias_max = 512
dry_seq_break_max = 128

# global vars
handle = None
friendlymodelname = "inactive"
friendlysdmodelname = "inactive"
lastgeneratedcomfyimg = b''
fullsdmodelpath = ""  #if empty, it's not initialized
mmprojpath = "" #if empty, it's not initialized
password = "" #if empty, no auth key required
fullwhispermodelpath = "" #if empty, it's not initialized
maxctx = 4096
maxhordectx = 4096
maxhordelen = 400
modelbusy = threading.Lock()
requestsinqueue = 0
defaultport = 5001
KcppVersion = "1.79.1"
showdebug = True
guimode = False
showsamplerwarning = True
showmaxctxwarning = True
showusedmemwarning = True
session_kudos_earned = 0
session_jobs = 0
session_starttime = None
exitcounter = -1
punishcounter = 0 #causes a timeout if too many errors
rewardcounter = 0 #reduces error counts for successful jobs
totalgens = 0
currentusergenkey = "" #store a special key so polled streaming works even in multiuser
pendingabortkey = "" #if an abort is received for the non-active request, remember it (at least 1) to cancel later
args = None #global args
runmode_untouched = True
modelfile_extracted_meta = None
importvars_in_progress = False
has_multiplayer = False
multiplayer_story_data_compressed = None #stores the full compressed story of the current multiplayer session
multiplayer_turn_major = 1 # to keep track of when a client needs to sync their stories
multiplayer_turn_minor = 1
multiplayer_dataformat = "" # used to tell what is the data payload in saved story. set by client
multiplayer_lastactive = {} # timestamp of last activity for each unique player
preloaded_story = None
chatcompl_adapter = None
embedded_kailite = None
embedded_kcpp_docs = None
embedded_kcpp_sdui = None
sslvalid = False
nocertify = False
start_time = time.time()
last_req_time = time.time()
last_non_horde_req_time = time.time()
currfinishreason = "null"
using_gui_launcher = False
using_outdated_flags = False

saved_stdout = None
saved_stderr = None
saved_stdout_py = None
saved_stderr_py = None
stdout_nullfile = None
stdout_nullfile_py = None

CLDevices = ["1","2","3","4"]
CUDevices = ["1","2","3","4","All"]
CLDevicesNames = ["","","",""]
CUDevicesNames = ["","","","",""]
VKDevicesNames = ["","","",""]
VKIsDGPU = [0,0,0,0]
MaxMemory = [0]
MaxFreeMemory = [0]

class logit_bias(ctypes.Structure):
    _fields_ = [("token_id", ctypes.c_int32),
                ("bias", ctypes.c_float)]

class token_count_outputs(ctypes.Structure):
    _fields_ = [("count", ctypes.c_int),
                ("ids", ctypes.POINTER(ctypes.c_int))]

# returns top 5 logprobs per token
class logprob_item(ctypes.Structure):
     _fields_ = [("option_count", ctypes.c_int),
                ("selected_token", ctypes.c_char_p),
                ("selected_logprob", ctypes.c_float),
                ("tokens", ctypes.c_char_p * logprobs_max),
                ("logprobs", ctypes.POINTER(ctypes.c_float))]
class last_logprobs_outputs(ctypes.Structure):
    _fields_ = [("count", ctypes.c_int),
                ("logprob_items", ctypes.POINTER(logprob_item))]

class load_model_inputs(ctypes.Structure):
    _fields_ = [("threads", ctypes.c_int),
                ("blasthreads", ctypes.c_int),
                ("max_context_length", ctypes.c_int),
                ("low_vram", ctypes.c_bool),
                ("use_mmq", ctypes.c_bool),
                ("use_rowsplit", ctypes.c_bool),
                ("executable_path", ctypes.c_char_p),
                ("model_filename", ctypes.c_char_p),
                ("lora_filename", ctypes.c_char_p),
                ("lora_base", ctypes.c_char_p),
                ("draftmodel_filename", ctypes.c_char_p),
                ("draft_amount", ctypes.c_int),
                ("mmproj_filename", ctypes.c_char_p),
                ("use_mmap", ctypes.c_bool),
                ("use_mlock", ctypes.c_bool),
                ("use_smartcontext", ctypes.c_bool),
                ("use_contextshift", ctypes.c_bool),
                ("use_fastforward", ctypes.c_bool),
                ("clblast_info", ctypes.c_int),
                ("cublas_info", ctypes.c_int),
                ("vulkan_info", ctypes.c_char_p),
                ("blasbatchsize", ctypes.c_int),
                ("debugmode", ctypes.c_int),
                ("forceversion", ctypes.c_int),
                ("gpulayers", ctypes.c_int),
                ("rope_freq_scale", ctypes.c_float),
                ("rope_freq_base", ctypes.c_float),
                ("flash_attention", ctypes.c_bool),
                ("tensor_split", ctypes.c_float * tensor_split_max),
                ("quant_k", ctypes.c_int),
                ("quant_v", ctypes.c_int)]

class generation_inputs(ctypes.Structure):
    _fields_ = [("seed", ctypes.c_int),
                ("prompt", ctypes.c_char_p),
                ("memory", ctypes.c_char_p),
                ("images", ctypes.c_char_p * images_max),
                ("max_context_length", ctypes.c_int),
                ("max_length", ctypes.c_int),
                ("temperature", ctypes.c_float),
                ("top_k", ctypes.c_int),
                ("top_a", ctypes.c_float),
                ("top_p", ctypes.c_float),
                ("min_p", ctypes.c_float),
                ("typical_p", ctypes.c_float),
                ("tfs", ctypes.c_float),
                ("rep_pen", ctypes.c_float),
                ("rep_pen_range", ctypes.c_int),
                ("rep_pen_slope", ctypes.c_float),
                ("presence_penalty", ctypes.c_float),
                ("mirostat", ctypes.c_int),
                ("mirostat_tau", ctypes.c_float),
                ("mirostat_eta", ctypes.c_float),
                ("xtc_threshold", ctypes.c_float),
                ("xtc_probability", ctypes.c_float),
                ("sampler_order", ctypes.c_int * sampler_order_max),
                ("sampler_len", ctypes.c_int),
                ("allow_eos_token", ctypes.c_bool),
                ("bypass_eos_token", ctypes.c_bool),
                ("render_special", ctypes.c_bool),
                ("stream_sse", ctypes.c_bool),
                ("grammar", ctypes.c_char_p),
                ("grammar_retain_state", ctypes.c_bool),
                ("quiet", ctypes.c_bool),
                ("dynatemp_range", ctypes.c_float),
                ("dynatemp_exponent", ctypes.c_float),
                ("smoothing_factor", ctypes.c_float),
                ("dry_multiplier", ctypes.c_float),
                ("dry_base", ctypes.c_float),
                ("dry_allowed_length", ctypes.c_int),
                ("dry_penalty_last_n", ctypes.c_int),
                ("dry_sequence_breakers_len", ctypes.c_int),
                ("dry_sequence_breakers", ctypes.POINTER(ctypes.c_char_p)),
                ("stop_sequence_len", ctypes.c_int),
                ("stop_sequence", ctypes.POINTER(ctypes.c_char_p)),
                ("logit_biases_len", ctypes.c_int),
                ("logit_biases", ctypes.POINTER(logit_bias)),
                ("banned_tokens_len", ctypes.c_int),
                ("banned_tokens", ctypes.POINTER(ctypes.c_char_p))]

class generation_outputs(ctypes.Structure):
    _fields_ = [("status", ctypes.c_int),
                ("stopreason", ctypes.c_int),
                ("prompt_tokens", ctypes.c_int),
                ("completion_tokens", ctypes.c_int),
                ("text", ctypes.c_char_p)]

class sd_load_model_inputs(ctypes.Structure):
    _fields_ = [("model_filename", ctypes.c_char_p),
                ("executable_path", ctypes.c_char_p),
                ("clblast_info", ctypes.c_int),
                ("cublas_info", ctypes.c_int),
                ("vulkan_info", ctypes.c_char_p),
                ("threads", ctypes.c_int),
                ("quant", ctypes.c_int),
                ("taesd", ctypes.c_bool),
                ("t5xxl_filename", ctypes.c_char_p),
                ("clipl_filename", ctypes.c_char_p),
                ("clipg_filename", ctypes.c_char_p),
                ("vae_filename", ctypes.c_char_p),
                ("lora_filename", ctypes.c_char_p),
                ("lora_multiplier", ctypes.c_float),
                ("debugmode", ctypes.c_int)]

class sd_generation_inputs(ctypes.Structure):
    _fields_ = [("prompt", ctypes.c_char_p),
                ("negative_prompt", ctypes.c_char_p),
                ("init_images", ctypes.c_char_p),
                ("denoising_strength", ctypes.c_float),
                ("cfg_scale", ctypes.c_float),
                ("sample_steps", ctypes.c_int),
                ("width", ctypes.c_int),
                ("height", ctypes.c_int),
                ("seed", ctypes.c_int),
                ("sample_method", ctypes.c_char_p),
                ("clip_skip", ctypes.c_int),
                ("quiet", ctypes.c_bool)]

class sd_generation_outputs(ctypes.Structure):
    _fields_ = [("status", ctypes.c_int),
                ("data", ctypes.c_char_p)]

class whisper_load_model_inputs(ctypes.Structure):
    _fields_ = [("model_filename", ctypes.c_char_p),
                ("executable_path", ctypes.c_char_p),
                ("clblast_info", ctypes.c_int),
                ("cublas_info", ctypes.c_int),
                ("vulkan_info", ctypes.c_char_p),
                ("debugmode", ctypes.c_int)]

class whisper_generation_inputs(ctypes.Structure):
    _fields_ = [("prompt", ctypes.c_char_p),
                ("audio_data", ctypes.c_char_p),
                ("quiet", ctypes.c_bool)]

class whisper_generation_outputs(ctypes.Structure):
    _fields_ = [("status", ctypes.c_int),
                ("data", ctypes.c_char_p)]

def getdirpath():
    return os.path.dirname(os.path.realpath(__file__))
def getabspath():
    return os.path.dirname(os.path.abspath(__file__))
def file_exists(filename):
    return os.path.exists(os.path.join(getdirpath(), filename))

def suppress_stdout():
    global saved_stdout, saved_stderr, saved_stdout_py, saved_stderr_py, stdout_nullfile, stdout_nullfile_py
    if not saved_stdout and not saved_stderr and not saved_stdout_py and not saved_stderr_py and not stdout_nullfile and not stdout_nullfile_py:
        sys.stdout.flush()
        sys.stderr.flush()
        saved_stdout = os.dup(sys.stdout.fileno())
        saved_stderr = os.dup(sys.stderr.fileno())
        saved_stderr_py = sys.stderr
        saved_stdout_py = sys.stdout
        stdout_nullfile = os.open(os.devnull, os.O_WRONLY)
        stdout_nullfile_py = open(os.devnull, 'w')
        os.dup2(stdout_nullfile, sys.stdout.fileno())
        os.dup2(stdout_nullfile, sys.stderr.fileno())
        sys.stderr = sys.stdout = stdout_nullfile_py

def restore_stdout():
    global saved_stdout, saved_stderr, saved_stdout_py, saved_stderr_py, stdout_nullfile, stdout_nullfile_py
    if saved_stdout and saved_stderr and saved_stdout_py and saved_stderr_py and stdout_nullfile and stdout_nullfile_py:
        sys.stdout = saved_stdout_py
        sys.stderr = saved_stderr_py
        os.dup2(saved_stdout, sys.stdout.fileno())
        os.dup2(saved_stderr, sys.stderr.fileno())
        os.close(stdout_nullfile)
        stdout_nullfile_py.close()
        os.close(saved_stdout)
        os.close(saved_stderr)
        saved_stdout = saved_stderr = saved_stdout_py = saved_stderr_py = stdout_nullfile = stdout_nullfile_py = None

def get_default_threads():
    physical_core_limit = 1
    if os.cpu_count()!=None and os.cpu_count()>1:
        physical_core_limit = os.cpu_count() // 2
    default_threads = (physical_core_limit if physical_core_limit<=3 else max(3,physical_core_limit-1))
    processor = platform.processor()
    if 'Intel' in processor:
        default_threads = (8 if default_threads > 8 else default_threads) #this helps avoid e-cores.
    return default_threads

def pick_existant_file(ntoption,nonntoption):
    precompiled_prefix = "precompiled_"
    ntexist = file_exists(ntoption)
    nonntexist = file_exists(nonntoption)
    precompiled_ntexist = file_exists(precompiled_prefix+ntoption)
    precompiled_nonntexist = file_exists(precompiled_prefix+nonntoption)
    if os.name == 'nt':
        if not ntexist and precompiled_ntexist:
            return (precompiled_prefix+ntoption)
        if nonntexist and not ntexist:
            return nonntoption
        return ntoption
    else:
        if not nonntexist and precompiled_nonntexist:
            return (precompiled_prefix+nonntoption)
        if ntexist and not nonntexist:
            return ntoption
        return nonntoption

lib_default = pick_existant_file("koboldcpp_default.dll","koboldcpp_default.so")
lib_failsafe = pick_existant_file("koboldcpp_failsafe.dll","koboldcpp_failsafe.so")
lib_noavx2 = pick_existant_file("koboldcpp_noavx2.dll","koboldcpp_noavx2.so")
lib_clblast = pick_existant_file("koboldcpp_clblast.dll","koboldcpp_clblast.so")
lib_clblast_noavx2 = pick_existant_file("koboldcpp_clblast_noavx2.dll","koboldcpp_clblast_noavx2.so")
lib_cublas = pick_existant_file("koboldcpp_cublas.dll","koboldcpp_cublas.so")
lib_hipblas = pick_existant_file("koboldcpp_hipblas.dll","koboldcpp_hipblas.so")
lib_vulkan = pick_existant_file("koboldcpp_vulkan.dll","koboldcpp_vulkan.so")
lib_vulkan_noavx2 = pick_existant_file("koboldcpp_vulkan_noavx2.dll","koboldcpp_vulkan_noavx2.so")
libname = ""
lib_option_pairs = [
    (lib_default, "Use CPU"),
    (lib_clblast, "Use CLBlast"),
    (lib_cublas, "Use CuBLAS"),
    (lib_hipblas, "Use hipBLAS (ROCm)"),
    (lib_vulkan, "Use Vulkan"),
    (lib_noavx2, "Use CPU (Old CPU)"),
    (lib_clblast_noavx2, "Use CLBlast (Old CPU)"),
    (lib_vulkan_noavx2, "Use Vulkan (Old CPU)"),
    (lib_failsafe, "Failsafe Mode (Old CPU)")]
default_option, clblast_option, cublas_option, hipblas_option, vulkan_option, noavx2_option, clblast_noavx2_option, vulkan_noavx2_option, failsafe_option = (opt if file_exists(lib) or (os.name == 'nt' and file_exists(opt + ".dll")) else None for lib, opt in lib_option_pairs)
runopts = [opt for lib, opt in lib_option_pairs if file_exists(lib)]

def init_library():
    global handle, args, libname
    global lib_default,lib_failsafe,lib_noavx2,lib_clblast,lib_clblast_noavx2,lib_cublas,lib_hipblas,lib_vulkan,lib_vulkan_noavx2

    libname = ""
    use_clblast = False #uses CLBlast instead
    use_cublas = False #uses cublas instead
    use_hipblas = False #uses hipblas instead
    use_noavx2 = False #uses no avx2 instructions
    use_failsafe = False #uses no intrinsics, failsafe mode
    use_vulkan = False #uses vulkan (needs avx2)

    if args.noavx2:
        use_noavx2 = True
        if args.useclblast:
            if not file_exists(lib_clblast_noavx2) or (os.name=='nt' and not file_exists("clblast.dll")):
                print("Warning: NoAVX2 CLBlast library file not found. CPU library will be used.")
            else:
                print("Attempting to use NoAVX2 CLBlast library for faster prompt ingestion. A compatible clblast will be required.")
                use_clblast = True
        elif (args.usevulkan is not None):
            if not file_exists(lib_vulkan_noavx2):
                print("Warning: NoAVX2 Vulkan library file not found. CPU library will be used.")
            else:
                print("Attempting to use NoAVX2 Vulkan library for faster prompt ingestion. A compatible Vulkan will be required.")
                use_vulkan = True
        else:
            if not file_exists(lib_noavx2):
                print("Warning: NoAVX2 library file not found. Failsafe library will be used.")
            elif (args.usecpu and args.nommap):
                use_failsafe = True
                print("!!! Attempting to use FAILSAFE MODE !!!")
            else:
                print("Attempting to use non-avx2 compatibility library.")
    elif (args.usecublas is not None):
        if not file_exists(lib_cublas) and not file_exists(lib_hipblas):
            print("Warning: CuBLAS library file not found. CPU library will be used.")
        else:
            if file_exists(lib_cublas):
                print("Attempting to use CuBLAS library for faster prompt ingestion. A compatible CuBLAS will be required.")
                use_cublas = True
            elif file_exists(lib_hipblas):
                print("Attempting to use hipBLAS library for faster prompt ingestion. A compatible AMD GPU will be required.")
                use_hipblas = True
    elif (args.usevulkan is not None):
        if not file_exists(lib_vulkan):
            print("Warning: Vulkan library file not found. CPU library will be used.")
        else:
            print("Attempting to use Vulkan library for faster prompt ingestion. A compatible Vulkan will be required.")
            use_vulkan = True
    elif args.useclblast:
        if not file_exists(lib_clblast) or (os.name=='nt' and not file_exists("clblast.dll")):
            print("Warning: CLBlast library file not found. CPU library will be used.")
        else:
            print("Attempting to use CLBlast library for faster prompt ingestion. A compatible clblast will be required.")
            use_clblast = True
    else:
        print("Attempting to use CPU library.")

    if use_noavx2:
        if use_failsafe:
            libname = lib_failsafe
        elif use_clblast:
            libname = lib_clblast_noavx2
        elif use_vulkan:
            libname = lib_vulkan_noavx2
        else:
            libname = lib_noavx2
    else:
        if use_clblast:
            libname = lib_clblast
        elif use_cublas:
            libname = lib_cublas
        elif use_hipblas:
            libname = lib_hipblas
        elif use_vulkan:
            libname = lib_vulkan
        else:
            libname = lib_default

    print("Initializing dynamic library: " + libname)
    dir_path = getdirpath()
    abs_path = getabspath()

    #add all potential paths
    if os.name=='nt':
        os.add_dll_directory(dir_path)
        os.add_dll_directory(abs_path)
        os.add_dll_directory(os.getcwd())
        if libname == lib_cublas and "CUDA_PATH" in os.environ:
            newpath = os.path.join(os.environ["CUDA_PATH"], "bin")
            if os.path.exists(newpath):
                os.add_dll_directory(newpath)
        if libname == lib_hipblas and "HIP_PATH" in os.environ:
            newpath = os.path.join(os.environ["HIP_PATH"], "bin")
            if os.path.exists(newpath):
                os.add_dll_directory(newpath)

    handle = ctypes.CDLL(os.path.join(dir_path, libname))

    handle.load_model.argtypes = [load_model_inputs]
    handle.load_model.restype = ctypes.c_bool
    handle.generate.argtypes = [generation_inputs]
    handle.generate.restype = generation_outputs
    handle.new_token.restype = ctypes.c_char_p
    handle.new_token.argtypes = [ctypes.c_int]
    handle.get_stream_count.restype = ctypes.c_int
    handle.has_finished.restype = ctypes.c_bool
    handle.get_last_eval_time.restype = ctypes.c_float
    handle.get_last_process_time.restype = ctypes.c_float
    handle.get_last_token_count.restype = ctypes.c_int
    handle.get_last_seed.restype = ctypes.c_int
    handle.get_total_gens.restype = ctypes.c_int
    handle.get_last_stop_reason.restype = ctypes.c_int
    handle.abort_generate.restype = ctypes.c_bool
    handle.token_count.restype = token_count_outputs
    handle.get_pending_output.restype = ctypes.c_char_p
    handle.get_chat_template.restype = ctypes.c_char_p
    handle.sd_load_model.argtypes = [sd_load_model_inputs]
    handle.sd_load_model.restype = ctypes.c_bool
    handle.sd_generate.argtypes = [sd_generation_inputs]
    handle.sd_generate.restype = sd_generation_outputs
    handle.whisper_load_model.argtypes = [whisper_load_model_inputs]
    handle.whisper_load_model.restype = ctypes.c_bool
    handle.whisper_generate.argtypes = [whisper_generation_inputs]
    handle.whisper_generate.restype = whisper_generation_outputs
    handle.last_logprobs.restype = last_logprobs_outputs
    handle.detokenize.argtypes = [token_count_outputs]
    handle.detokenize.restype = ctypes.c_char_p

def set_backend_props(inputs):
    clblastids = 0
    if args.useclblast:
        clblastids = 100 + int(args.useclblast[0])*10 + int(args.useclblast[1])
    inputs.clblast_info = clblastids

    # we must force an explicit tensor split
    # otherwise the default will divide equally and multigpu crap will slow it down badly
    inputs.cublas_info = 0

    if not args.tensor_split:
        if (args.usecublas and "0" in args.usecublas):
            os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
            os.environ["CUDA_VISIBLE_DEVICES"] = "0"
            os.environ["HIP_VISIBLE_DEVICES"] = "0"
        elif (args.usecublas and "1" in args.usecublas):
            os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
            os.environ["CUDA_VISIBLE_DEVICES"] = "1"
            os.environ["HIP_VISIBLE_DEVICES"] = "1"
        elif (args.usecublas and "2" in args.usecublas):
            os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
            os.environ["CUDA_VISIBLE_DEVICES"] = "2"
            os.environ["HIP_VISIBLE_DEVICES"] = "2"
        elif (args.usecublas and "3" in args.usecublas):
            os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
            os.environ["CUDA_VISIBLE_DEVICES"] = "3"
            os.environ["HIP_VISIBLE_DEVICES"] = "3"
    else:
        if (args.usecublas and "0" in args.usecublas):
            os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
            inputs.cublas_info = 0
        elif (args.usecublas and "1" in args.usecublas):
            os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
            inputs.cublas_info = 1
        elif (args.usecublas and "2" in args.usecublas):
            os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
            inputs.cublas_info = 2
        elif (args.usecublas and "3" in args.usecublas):
            os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
            inputs.cublas_info = 3

    if args.usevulkan: #is an empty array if using vulkan without defined gpu
        s = ""
        for l in range(0,len(args.usevulkan)):
            s += str(args.usevulkan[l])
        inputs.vulkan_info = s.encode("UTF-8")
    else:
        inputs.vulkan_info = "".encode("UTF-8")
    return inputs

def end_trim_to_sentence(input_text):
    enders = ['.', '!', '?', '*', '"', ')', '}', '`', ']', ';', '…']
    last = -1
    for ender in enders:
        last = max(last, input_text.rfind(ender))
    nl = input_text.rfind("\n")
    last = max(last, nl)
    if last > 0:
        return input_text[:last + 1].strip()
    return input_text.strip()

def tryparseint(value):
    try:
        return int(value)
    except ValueError:
        return value

def is_incomplete_utf8_sequence(byte_seq): #note, this will only flag INCOMPLETE sequences, corrupted ones will be ignored.
    try:
        byte_seq.decode('utf-8')
        return False  # Valid UTF-8
    except UnicodeDecodeError as e:
        if e.reason == 'unexpected end of data':
            return True #incomplete sequence
        return False #invalid sequence, but not incomplete

def unpack_to_dir(destpath = ""):
    import shutil
    srcpath = os.path.abspath(os.path.dirname(__file__))
    cliunpack = False if destpath == "" else True
    print("Attempt to unpack KoboldCpp into directory...")

    if not cliunpack:
        from tkinter.filedialog import askdirectory
        from tkinter import messagebox
        destpath = askdirectory(title='Select an empty folder to unpack KoboldCpp')
        if not destpath:
            return

    if os.path.isdir(srcpath) and os.path.isdir(destpath) and not os.listdir(destpath):
        try:
            if cliunpack:
                print(f"KoboldCpp will be extracted to {destpath}\nThis process may take several seconds to complete.")
            else:
                messagebox.showinfo("Unpack Starting", f"KoboldCpp will be extracted to {destpath}\nThis process may take several seconds to complete.")
            for item in os.listdir(srcpath):
                s = os.path.join(srcpath, item)
                d = os.path.join(destpath, item)
                if item.endswith('.pyd'):  # Skip .pyd files
                    continue
                if os.path.isdir(s):
                    shutil.copytree(s, d, False, None)
                else:
                    shutil.copy2(s, d)
            if cliunpack:
                print(f"KoboldCpp successfully extracted to {destpath}")
            else:
                messagebox.showinfo("KoboldCpp Unpack Success", f"KoboldCpp successfully extracted to {destpath}")
        except Exception as e:
            if cliunpack:
                print(f"An error occurred while unpacking: {e}")
            else:
                messagebox.showerror("Error", f"An error occurred while unpacking: {e}")
    else:
        if cliunpack:
            print(f"The target folder is not empty or invalid. Please select an empty folder.")
        else:
            messagebox.showwarning("Invalid Selection", "The target folder is not empty or invalid. Please select an empty folder.")

def exit_with_error(code, message, title="Error"):
    global guimode
    print("")
    time.sleep(1)
    if guimode:
        show_gui_msgbox(title, message)
    else:
        print(message, flush=True)
    time.sleep(2)
    sys.exit(code)

def utfprint(str):
    maxlen = 32000
    if args.debugmode >= 1:
        maxlen = 64000
    strlength = len(str)
    if strlength > maxlen: #limit max output len
        str = str[:maxlen] + f"... (+{strlength-maxlen} chars)"
    try:
        print(str)
    except UnicodeEncodeError:
        # Replace or omit the problematic character
        utf_string = str.encode('ascii', 'ignore').decode('ascii',"ignore")
        utf_string = utf_string.replace('\a', '') #remove bell characters
        print(utf_string)

def bring_terminal_to_foreground():
    if os.name=='nt':
        ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 9)
        ctypes.windll.user32.SetForegroundWindow(ctypes.windll.kernel32.GetConsoleWindow())

def string_has_overlap(str_a, str_b, maxcheck):
    max_overlap = min(maxcheck, len(str_a), len(str_b))
    for i in range(1, max_overlap + 1):
        if str_a[-i:] == str_b[:i]:
            return True
    return False

def string_contains_or_overlaps_sequence_substring(inputstr, sequences):
    if inputstr=="":
        return False
    for s in sequences:
        if s.strip()=="":
            continue
        if s.strip() in inputstr.strip() or inputstr.strip() in s.strip():
            return True
        if string_has_overlap(inputstr, s, 10):
            return True
    return False

import struct

def read_gguf_metadata(file_path):
    chunk_size = 8192  # read only first 8kb of file
    try:
        def read_gguf_key(keyname,data,maxval):
            keylen = len(keyname)
            index = data.find(keyname)  # Search for the magic number, Read 2 chunks of 4 byte numbers
            if index != -1 and index + keylen + 8 <= chunk_size:
                start_index = index + keylen
                first_value_bytes = data[start_index:start_index + 4]
                second_value_bytes = data[start_index + 4:start_index + 8]
                # Unpack each 4 bytes as an unsigned int32 in little-endian format
                value1 = struct.unpack('<I', first_value_bytes)[0] #4 means its a uint32
                value2 = struct.unpack('<I', second_value_bytes)[0]
                if value1 == 4 and value2 > 0 and value2 <= maxval:
                    return value2 #contains the desired value
                return 0
            else:
                return 0 #not found

        fsize = os.path.getsize(file_path)
        if fsize < 10000: #ignore files under 10kb
            return None
        with open(file_path, 'rb') as f:
            file_header = f.read(4)
            if file_header != b'GGUF': #file is not GGUF
                return None
            data = f.read(chunk_size)
            layercount = read_gguf_key(b'.block_count',data,512)
            head_count_kv = read_gguf_key(b'.attention.head_count_kv',data,8192)
            key_length = read_gguf_key(b'.attention.key_length',data,8192)
            val_length = read_gguf_key(b'.attention.value_length',data,8192)
            return [layercount,head_count_kv, max(key_length,val_length)]
    except Exception as ex:
        return None

def extract_modelfile_params(filepath,sdfilepath,whisperfilepath,mmprojfilepath,draftmodelpath):
    global modelfile_extracted_meta
    modelfile_extracted_meta = None
    sdfsize = 0
    whisperfsize = 0
    mmprojsize = 0
    draftmodelsize = 0
    if sdfilepath and os.path.exists(sdfilepath):
        sdfsize = os.path.getsize(sdfilepath)
    if whisperfilepath and os.path.exists(whisperfilepath):
        whisperfsize = os.path.getsize(whisperfilepath)
    if mmprojfilepath and os.path.exists(mmprojfilepath):
        mmprojsize = os.path.getsize(mmprojfilepath)
    if draftmodelpath and os.path.exists(draftmodelpath):
        draftmodelsize = os.path.getsize(draftmodelpath)
    if filepath and os.path.exists(filepath):
        try:
            fsize = os.path.getsize(filepath)
            if fsize>10000000: #dont bother with models < 10mb as they are probably bad
                ggufmeta = read_gguf_metadata(filepath)
                modelfile_extracted_meta = [ggufmeta,fsize,sdfsize,whisperfsize,mmprojsize,draftmodelsize] #extract done. note that meta may be null
        except Exception as ex:
            modelfile_extracted_meta = None

def autoset_gpu_layers(ctxsize,sdquanted,bbs): #shitty algo to determine how many layers to use
    global showusedmemwarning, modelfile_extracted_meta # reference cached values instead
    gpumem = MaxMemory[0]
    usedmem = 0
    if MaxFreeMemory[0]>0:
        usedmem = MaxMemory[0]-MaxFreeMemory[0]
        if showusedmemwarning and usedmem > (2.5*1024*1024*1024):
            showusedmemwarning = False
            print(f"Note: KoboldCpp has detected that a significant amount of GPU VRAM ({usedmem/1024/1024} MB) is currently used by another application.\nFor best results, you may wish to close that application and then restart KoboldCpp.\n***")
    reservedmem = max(1.3*1024*1024*1024,(0.5*1024*1024*1024 + usedmem)) # determine vram overhead
    try:
        if not modelfile_extracted_meta:
            return 0
        layerlimit = 0
        fsize = modelfile_extracted_meta[1]
        if fsize>10000000: #dont bother with models < 10mb
            cs = ctxsize
            mem = gpumem
            if modelfile_extracted_meta[2] > 1024*1024*1024*5: #sdxl tax
                mem -= 1024*1024*1024*(6 if sdquanted else 9)
            elif modelfile_extracted_meta[2] > 1024*1024*512: #normal sd tax
                mem -= 1024*1024*1024*(3.25 if sdquanted else 4.25)
            if modelfile_extracted_meta[3] > 1024*1024*10: #whisper tax
                mem -= 350*1024*1024
            if modelfile_extracted_meta[4] > 1024*1024*10: #mmproj tax
                mem -= 350*1024*1024
            if modelfile_extracted_meta[5] > 1024*1024*10: #draft model tax
                mem -= (modelfile_extracted_meta[5] * 1.5)
            mem = 0 if mem < 0 else mem

            csmul = 1.0
            if cs:
                csmul = (cs/4096) if cs >= 8192 else 1.8 if cs > 4096 else 1.2 if cs > 2048 else 1.0
            ggufmeta = modelfile_extracted_meta[0]
            if not ggufmeta or ggufmeta[0]==0: #fail to read or no layers
                sizeperlayer = fsize*csmul*0.052
                layerlimit = int(min(200,(mem-usedmem)/sizeperlayer))
            else:
                layers = ggufmeta[0]
                headcount = ggufmeta[1]
                headkvlen = (ggufmeta[2] if ggufmeta[2] > 0 else 128)
                ratio = (mem-usedmem)/(fsize*csmul*1.6*(1.0 if bbs <= 512 else 1.2))
                computemem = layers*(4 if bbs <= 512 else (bbs/128))*headkvlen*cs*4*1.55 # apply blasbatchsize calculations if over 512
                contextmem = layers*headcount*headkvlen*cs*4*1.15
                if headcount > 0:
                    ratio = max(ratio, (mem - reservedmem - computemem) / (fsize + contextmem))
                layerlimit = min(int(ratio*layers), (layers + 3))
        layerlimit = (0 if layerlimit<=2 else layerlimit)
        return layerlimit
    except Exception as ex:
        return 0

def fetch_gpu_properties(testCL,testCU,testVK):
    import subprocess

    if testCU:
        FetchedCUdevices = []
        FetchedCUdeviceMem = []
        FetchedCUfreeMem = []
        AMDgpu = None
        try: # Get NVIDIA GPU names
            output = subprocess.run(['nvidia-smi','--query-gpu=name,memory.total,memory.free','--format=csv,noheader'], capture_output=True, text=True, check=True, encoding='utf-8').stdout
            FetchedCUdevices = [line.split(",")[0].strip() for line in output.splitlines()]
            FetchedCUdeviceMem = [line.split(",")[1].strip().split(" ")[0].strip() for line in output.splitlines()]
            FetchedCUfreeMem = [line.split(",")[2].strip().split(" ")[0].strip() for line in output.splitlines()]
        except Exception as e:
            pass
        if len(FetchedCUdevices)==0:
            try: # Get AMD ROCm GPU names
                output = subprocess.run(['rocminfo'], capture_output=True, text=True, check=True, encoding='utf-8').stdout
                device_name = None
                for line in output.splitlines(): # read through the output line by line
                    line = line.strip()
                    if line.startswith("Marketing Name:"): device_name = line.split(":", 1)[1].strip() # if we find a named device, temporarily save the name
                    elif line.startswith("Device Type:") and "GPU" in line and device_name is not None: # if the following Device Type is a GPU (not a CPU) then add it to devices list
                        FetchedCUdevices.append(device_name)
                        AMDgpu = True
                    elif line.startswith("Device Type:") and "GPU" not in line: device_name = None
                if FetchedCUdevices:
                    getamdvram = subprocess.run(['rocm-smi', '--showmeminfo', 'vram', '--csv'], capture_output=True, text=True, check=True, encoding='utf-8').stdout # fetch VRAM of devices
                    if getamdvram:
                        FetchedCUdeviceMem = [line.split(",")[1].strip() for line in getamdvram.splitlines()[1:] if line.strip()]
            except Exception as e:
                pass
        lowestcumem = 0
        lowestfreecumem = 0
        for idx in range(0,4):
            if(len(FetchedCUdevices)>idx):
                CUDevicesNames[idx] = FetchedCUdevices[idx]
                if len(FetchedCUdeviceMem)>idx:
                    dmem = int(FetchedCUdeviceMem[idx]) if AMDgpu else (int(FetchedCUdeviceMem[idx])*1024*1024)
                    lowestcumem = dmem if lowestcumem==0 else (dmem if dmem<lowestcumem else lowestcumem)
                if len(FetchedCUfreeMem)>idx:
                    dmem = (int(FetchedCUfreeMem[idx])*1024*1024)
                    lowestfreecumem = dmem if lowestfreecumem==0 else (dmem if dmem<lowestfreecumem else lowestfreecumem)

        MaxMemory[0] = max(lowestcumem,MaxMemory[0])
        MaxFreeMemory[0] = max(lowestfreecumem,MaxFreeMemory[0])

    if testVK:
        try: # Get Vulkan names
            output = subprocess.run(['vulkaninfo','--summary'], capture_output=True, text=True, check=True, encoding='utf-8').stdout
            devicelist = [line.split("=")[1].strip() for line in output.splitlines() if "deviceName" in line]
            devicetypes = [line.split("=")[1].strip() for line in output.splitlines() if "deviceType" in line]
            idx = 0
            for dname in devicelist:
                if idx<len(VKDevicesNames):
                    VKDevicesNames[idx] = dname
                    idx += 1
            if len(devicetypes) == len(devicelist):
                idx = 0
                for dvtype in devicetypes:
                    if idx<len(VKIsDGPU):
                        VKIsDGPU[idx] = (1 if dvtype=="PHYSICAL_DEVICE_TYPE_DISCRETE_GPU" else 0)
                        idx += 1
        except Exception as e:
            pass

    if testCL:
        try: # Get OpenCL GPU names on windows using a special binary. overwrite at known index if found.
            basepath = os.path.abspath(os.path.dirname(__file__))
            output = ""
            data = None
            try:
                output = subprocess.run(["clinfo","--json"], capture_output=True, text=True, check=True, encoding='utf-8').stdout
                data = json.loads(output)
            except Exception as e1:
                output = subprocess.run([((os.path.join(basepath, "winclinfo.exe")) if os.name == 'nt' else "clinfo"),"--json"], capture_output=True, text=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS, encoding='utf-8').stdout
                data = json.loads(output)
            plat = 0
            dev = 0
            lowestclmem = 0
            for platform in data["devices"]:
                dev = 0
                for device in platform["online"]:
                    dname = device["CL_DEVICE_NAME"]
                    dmem = int(device["CL_DEVICE_GLOBAL_MEM_SIZE"])
                    idx = plat+dev*2
                    if idx<len(CLDevices):
                        CLDevicesNames[idx] = dname
                        lowestclmem = dmem if lowestclmem==0 else (dmem if dmem<lowestclmem else lowestclmem)
                    dev += 1
                plat += 1
            MaxMemory[0] = max(lowestclmem,MaxMemory[0])
        except Exception as e:
            pass
    return

def auto_set_backend_cli():
    fetch_gpu_properties(False,True,True)
    found_new_backend = False
    if exitcounter < 100 and MaxMemory[0]>3500000000 and (("Use CuBLAS" in runopts and CUDevicesNames[0]!="") or "Use hipBLAS (ROCm)" in runopts) and any(CUDevicesNames):
        if "Use CuBLAS" in runopts or "Use hipBLAS (ROCm)" in runopts:
            args.usecublas = ["normal","mmq"]
            print("Auto Selected CUDA Backend...\n")
            found_new_backend = True
    elif exitcounter < 100 and (1 in VKIsDGPU) and "Use Vulkan" in runopts:
        for i in range(0,len(VKIsDGPU)):
            if VKIsDGPU[i]==1:
                args.usevulkan = []
                print("Auto Selected Vulkan Backend...\n")
                found_new_backend = True
                break
    if not found_new_backend:
        print("No GPU Backend found...\n")

def load_model(model_filename):
    global args
    inputs = load_model_inputs()
    inputs.model_filename = model_filename.encode("UTF-8")
    inputs.max_context_length = maxctx #initial value to use for ctx, can be overwritten
    inputs.threads = args.threads
    inputs.low_vram = (True if (args.usecublas and "lowvram" in args.usecublas) else False)
    inputs.use_mmq = (True if (args.usecublas and "mmq" in args.usecublas) else False)
    inputs.use_rowsplit = (True if (args.usecublas and "rowsplit" in args.usecublas) else False)
    inputs.vulkan_info = "0".encode("UTF-8")
    inputs.blasthreads = args.blasthreads
    inputs.use_mmap = (not args.nommap)
    inputs.use_mlock = args.usemlock
    inputs.lora_filename = "".encode("UTF-8")
    inputs.lora_base = "".encode("UTF-8")
    if args.lora:
        inputs.lora_filename = args.lora[0].encode("UTF-8")
        inputs.use_mmap = False
        if len(args.lora) > 1:
            inputs.lora_base = args.lora[1].encode("UTF-8")

    inputs.draftmodel_filename = args.draftmodel.encode("UTF-8") if args.draftmodel else "".encode("UTF-8")
    inputs.draft_amount = args.draftamount
    inputs.mmproj_filename = args.mmproj.encode("UTF-8") if args.mmproj else "".encode("UTF-8")
    inputs.use_smartcontext = args.smartcontext
    inputs.use_contextshift = (0 if args.noshift else 1)
    inputs.use_fastforward = (0 if args.nofastforward else 1)
    inputs.flash_attention = args.flashattention
    if args.quantkv>0:
        inputs.quant_k = inputs.quant_v = args.quantkv
        inputs.flash_attention = True
        inputs.use_contextshift = 0
    else:
        inputs.quant_k = inputs.quant_v = 0
    inputs.blasbatchsize = args.blasbatchsize
    inputs.forceversion = args.forceversion
    inputs.gpulayers = args.gpulayers
    inputs.rope_freq_scale = args.ropeconfig[0]
    if len(args.ropeconfig)>1:
        inputs.rope_freq_base = args.ropeconfig[1]
    else:
        inputs.rope_freq_base = 10000

    for n in range(tensor_split_max):
        if args.tensor_split and n < len(args.tensor_split):
            inputs.tensor_split[n] = float(args.tensor_split[n])
        else:
            inputs.tensor_split[n] = 0

    inputs = set_backend_props(inputs)

    inputs.executable_path = (getdirpath()+"/").encode("UTF-8")
    inputs.debugmode = args.debugmode
    ret = handle.load_model(inputs)
    return ret

def generate(genparams, is_quiet=False, stream_flag=False):
    global maxctx, args, currentusergenkey, totalgens, pendingabortkey

    prompt = genparams.get('prompt', "")
    memory = genparams.get('memory', "")
    images = genparams.get('images', [])
    max_context_length = genparams.get('max_context_length', maxctx)
    max_length = genparams.get('max_length', 200)
    temperature = genparams.get('temperature', 0.7)
    top_k = genparams.get('top_k', 100)
    top_a = genparams.get('top_a', 0.0)
    top_p = genparams.get('top_p', 0.92)
    min_p = genparams.get('min_p', 0.0)
    typical_p = genparams.get('typical', 1.0)
    tfs = genparams.get('tfs', 1.0)
    rep_pen = genparams.get('rep_pen', 1.0)
    rep_pen_range = genparams.get('rep_pen_range', 320)
    rep_pen_slope = genparams.get('rep_pen_slope', 1.0)
    presence_penalty = genparams.get('presence_penalty', 0.0)
    mirostat = genparams.get('mirostat', 0)
    mirostat_tau = genparams.get('mirostat_tau', 5.0)
    mirostat_eta = genparams.get('mirostat_eta', 0.1)
    dry_multiplier = genparams.get('dry_multiplier', 0.0)
    dry_base = genparams.get('dry_base', 1.75)
    dry_allowed_length = genparams.get('dry_allowed_length', 2)
    dry_penalty_last_n = genparams.get('dry_penalty_last_n', 320)
    dry_sequence_breakers = genparams.get('dry_sequence_breakers', [])
    xtc_threshold = genparams.get('xtc_threshold', 0.2)
    xtc_probability = genparams.get('xtc_probability', 0)
    sampler_order = genparams.get('sampler_order', [6, 0, 1, 3, 4, 2, 5])
    seed = tryparseint(genparams.get('sampler_seed', -1))
    stop_sequence = genparams.get('stop_sequence', [])
    ban_eos_token = genparams.get('ban_eos_token', False)
    stream_sse = stream_flag
    grammar = genparams.get('grammar', '')
    grammar_retain_state = genparams.get('grammar_retain_state', False)
    genkey = genparams.get('genkey', '')
    trimstop = genparams.get('trim_stop', False)
    quiet = is_quiet
    dynatemp_range = genparams.get('dynatemp_range', 0.0)
    dynatemp_exponent = genparams.get('dynatemp_exponent', 1.0)
    smoothing_factor = genparams.get('smoothing_factor', 0.0)
    logit_biases = genparams.get('logit_bias', {})
    render_special = genparams.get('render_special', False)
    banned_strings = genparams.get('banned_strings', []) # SillyTavern uses that name
    banned_tokens = genparams.get('banned_tokens', banned_strings)
    bypass_eos_token = genparams.get('bypass_eos', False)
    custom_token_bans = genparams.get('custom_token_bans', '')

    for tok in custom_token_bans.split(','):
        tok = tok.strip()  # Remove leading/trailing whitespace
        if tok.isdigit():
            logit_biases[tok] = bias_min_value

    inputs = generation_inputs()
    inputs.prompt = prompt.encode("UTF-8")
    inputs.memory = memory.encode("UTF-8")
    for n in range(images_max):
        if not images or n >= len(images):
            inputs.images[n] = "".encode("UTF-8")
        else:
            inputs.images[n] = images[n].encode("UTF-8")
    global showmaxctxwarning
    if max_context_length > maxctx:
        if showmaxctxwarning:
            print(f"\n(Warning! Request max_context_length={max_context_length} exceeds allocated context size of {maxctx}. It will be reduced to fit. Consider launching with increased --contextsize to avoid errors. This message will only show once per session.)")
            showmaxctxwarning = False
        max_context_length = maxctx
    min_remain = min(max_context_length-4, 16)
    if max_length >= (max_context_length-min_remain):
        max_length = max_context_length-min_remain
        print("\nWarning: You are trying to generate with max_length near or exceeding max_context_length. Most of the context will be removed, and your outputs will not be very coherent.")

    inputs.max_context_length = max_context_length   # this will resize the context buffer if changed
    inputs.max_length = max_length
    inputs.temperature = temperature
    inputs.top_k = top_k
    inputs.top_a = top_a
    inputs.top_p = top_p
    inputs.min_p = min_p
    inputs.typical_p = typical_p
    inputs.tfs = tfs
    inputs.rep_pen = rep_pen
    inputs.rep_pen_range = rep_pen_range
    inputs.rep_pen_slope = rep_pen_slope
    inputs.presence_penalty = presence_penalty
    inputs.stream_sse = stream_sse
    inputs.quiet = quiet
    inputs.dynatemp_range = dynatemp_range
    inputs.dynatemp_exponent = dynatemp_exponent
    inputs.smoothing_factor = smoothing_factor
    inputs.grammar = grammar.encode("UTF-8")
    inputs.grammar_retain_state = grammar_retain_state
    inputs.allow_eos_token = not ban_eos_token
    inputs.bypass_eos_token = bypass_eos_token
    inputs.render_special = render_special
    if mirostat in (1, 2):
        inputs.mirostat = mirostat
        inputs.mirostat_tau = mirostat_tau
        inputs.mirostat_eta = mirostat_eta
    else:
        inputs.mirostat = inputs.mirostat_tau = inputs.mirostat_eta = 0
    inputs.dry_multiplier = dry_multiplier
    inputs.dry_base = dry_base
    inputs.xtc_threshold = xtc_threshold
    inputs.xtc_probability = xtc_probability
    inputs.dry_allowed_length = dry_allowed_length
    inputs.dry_penalty_last_n = dry_penalty_last_n
    # Handle dry_sequence_breakers being passed as a json-encoded array of
    # strings, rather than as an array of strings itself. This is to support
    # SillyTavern, which passes sequence breakers to Oobabooga that way.
    if dry_multiplier > 0 and isinstance(dry_sequence_breakers, str):
        try:
            dry_sequence_breakers = json.loads(dry_sequence_breakers)
        except ValueError as e:
            print(f"ERROR: dry_sequence_breakers must be an array of strings or a json encoded array of strings. Could not parse '{dry_sequence_breakers}': " + str(e))
            dry_sequence_breakers = []

    if dry_multiplier <= 0 or dry_sequence_breakers is None: # prevent explicitly set to None, retain old behavior
        dry_sequence_breakers = []

    dry_sequence_breakers = dry_sequence_breakers[:dry_seq_break_max]
    inputs.dry_sequence_breakers_len = len(dry_sequence_breakers)
    inputs.dry_sequence_breakers = (ctypes.c_char_p * inputs.dry_sequence_breakers_len)()

    for n, breaker in enumerate(dry_sequence_breakers):
        inputs.dry_sequence_breakers[n] = breaker.encode("UTF-8")

    if sampler_order and 0 < len(sampler_order) <= sampler_order_max:
        try:
            for i, sampler in enumerate(sampler_order):
                inputs.sampler_order[i] = sampler
            inputs.sampler_len = len(sampler_order)
            global showsamplerwarning
            if showsamplerwarning and inputs.mirostat==0 and inputs.sampler_len>0 and (inputs.sampler_order[0]!=6 or inputs.sampler_order[inputs.sampler_len-1]!=5):
                print("\n(Note: Non-default sampler_order detected. Recommended sampler values are [6,0,1,3,4,2,5]. This message will only show once per session.)")
                showsamplerwarning = False
        except TypeError as e:
            print("ERROR: sampler_order must be a list of integers: " + str(e))
    inputs.seed = seed

    if stop_sequence is None:
        stop_sequence = []
    stop_sequence = stop_sequence[:stop_token_max]
    inputs.stop_sequence_len = len(stop_sequence)
    inputs.stop_sequence = (ctypes.c_char_p * inputs.stop_sequence_len)()

    for n, sequence in enumerate(stop_sequence):
        if sequence:
            inputs.stop_sequence[n] = sequence.encode("UTF-8")
        else:
            inputs.stop_sequence[n] = "".encode("UTF-8")

    bias_list = []
    try:
        if logit_biases and len(logit_biases) > 0:
            bias_list = [{"key": key, "value": value} for key, value in logit_biases.items()]
    except Exception as ex:
        print(f"Logit bias dictionary is invalid: {ex}")

    bias_list = bias_list[:logit_bias_max]
    inputs.logit_biases_len = len(bias_list)
    inputs.logit_biases = (logit_bias * inputs.logit_biases_len)()
    for n, lb in enumerate(bias_list):
        try:
            t_id = int(lb['key'])
            bias = float(lb['value'])
            t_id = -1 if t_id < 0 else t_id
            bias = (bias_max_value if bias > bias_max_value else (bias_min_value if bias < bias_min_value else bias))
            inputs.logit_biases[n] = logit_bias(t_id, bias)
        except Exception as ex:
            inputs.logit_biases[n] = logit_bias(-1, 0.0)
            print(f"Skipped unparsable logit bias:{ex}")

    if banned_tokens is None:
        banned_tokens = []
    banned_tokens = banned_tokens[:ban_token_max]
    inputs.banned_tokens_len = len(banned_tokens)
    inputs.banned_tokens = (ctypes.c_char_p * inputs.banned_tokens_len)()
    for n, tok in enumerate(banned_tokens):
        inputs.banned_tokens[n] = tok.encode("UTF-8")

    currentusergenkey = genkey
    totalgens += 1
    #early exit if aborted

    if pendingabortkey!="" and pendingabortkey==genkey:
        print(f"\nDeferred Abort for GenKey: {pendingabortkey}")
        pendingabortkey = ""
        return {"text":"","status":-1,"stopreason":-1, "prompt_tokens":0, "completion_tokens": 0, "total_tokens": 0}
    else:
        ret = handle.generate(inputs)
        outstr = ""
        if ret.status==1:
            outstr = ret.text.decode("UTF-8","ignore")
        if trimstop:
            for trim_str in stop_sequence:
                sindex = outstr.find(trim_str)
                if sindex != -1 and trim_str!="":
                    outstr = outstr[:sindex]
        return {"text":outstr,"status":ret.status,"stopreason":ret.stopreason,"prompt_tokens":ret.prompt_tokens, "completion_tokens": ret.completion_tokens}


def sd_load_model(model_filename,vae_filename,lora_filename,t5xxl_filename,clipl_filename,clipg_filename):
    global args
    inputs = sd_load_model_inputs()
    inputs.debugmode = args.debugmode
    inputs.executable_path = (getdirpath()+"/").encode("UTF-8")
    inputs.model_filename = model_filename.encode("UTF-8")
    thds = args.threads
    quant = 0

    if args.sdthreads and args.sdthreads > 0:
        sdt = int(args.sdthreads)
        if sdt > 0:
            thds = sdt
    if args.sdquant:
        quant = 1

    inputs.threads = thds
    inputs.quant = quant
    inputs.taesd = True if args.sdvaeauto else False
    inputs.vae_filename = vae_filename.encode("UTF-8")
    inputs.lora_filename = lora_filename.encode("UTF-8")
    inputs.lora_multiplier = args.sdloramult
    inputs.t5xxl_filename = t5xxl_filename.encode("UTF-8")
    inputs.clipl_filename = clipl_filename.encode("UTF-8")
    inputs.clipg_filename = clipg_filename.encode("UTF-8")
    inputs = set_backend_props(inputs)
    ret = handle.sd_load_model(inputs)
    return ret

def sd_comfyui_tranform_params(genparams):
    promptobj = genparams.get('prompt', None)
    if promptobj and isinstance(promptobj, dict):
        temp = promptobj.get('3', {})
        temp = temp.get('inputs', {})
        genparams["seed"] = temp.get("seed", -1)
        genparams["steps"] = temp.get("steps", 20)
        genparams["cfg_scale"] = temp.get("cfg", 5)
        genparams["sampler_name"] = temp.get("sampler_name", "euler")
        temp = promptobj.get('5', {})
        temp = temp.get('inputs', {})
        genparams["width"] = temp.get("width", 512)
        genparams["height"] = temp.get("height", 512)
        temp = promptobj.get('6', {})
        temp = temp.get('inputs', {})
        genparams["prompt"] = temp.get("text", "high quality")
        temp = promptobj.get('7', {})
        temp = temp.get('inputs', {})
        genparams["negative_prompt"] = temp.get("text", "")
    else:
        print("Warning: ComfyUI Payload Missing!")
    return genparams

def sd_generate(genparams):
    global maxctx, args, currentusergenkey, totalgens, pendingabortkey, chatcompl_adapter

    default_adapter = {} if chatcompl_adapter is None else chatcompl_adapter
    adapter_obj = genparams.get('adapter', default_adapter)
    forced_negprompt = adapter_obj.get("add_sd_negative_prompt", "")
    forced_posprompt = adapter_obj.get("add_sd_prompt", "")

    prompt = genparams.get("prompt", "high quality")
    negative_prompt = genparams.get("negative_prompt", "")
    if forced_negprompt!="":
        if negative_prompt!="":
            negative_prompt += ", " + forced_negprompt
        else:
            negative_prompt = forced_negprompt
    if forced_posprompt!="":
        if prompt!="":
            prompt += ", " + forced_posprompt
        else:
            prompt = forced_posprompt
    init_images_arr = genparams.get("init_images", [])
    init_images = ("" if (not init_images_arr or len(init_images_arr)==0 or not init_images_arr[0]) else init_images_arr[0])
    denoising_strength = genparams.get("denoising_strength", 0.6)
    cfg_scale = genparams.get("cfg_scale", 5)
    sample_steps = tryparseint(genparams.get("steps", 20))
    width = tryparseint(genparams.get("width", 512))
    height = tryparseint(genparams.get("height", 512))
    seed = tryparseint(genparams.get("seed", -1))
    sample_method = genparams.get("sampler_name", "k_euler_a")
    is_quiet = True if (args.quiet or args.debugmode == -1) else False
    clip_skip = tryparseint(genparams.get("clip_skip", -1))

    #clean vars
    width = width - (width%64)
    height = height - (height%64)
    cfg_scale = (1 if cfg_scale < 1 else (25 if cfg_scale > 25 else cfg_scale))
    sample_steps = (1 if sample_steps < 1 else (80 if sample_steps > 80 else sample_steps))
    reslimit = 1024
    width = (64 if width < 64 else width)
    height = (64 if height < 64 else height)

    if args.sdclamped:
        sample_steps = (40 if sample_steps > 40 else sample_steps)
        reslimit = int(args.sdclamped)
        reslimit = (512 if reslimit<512 else reslimit)
        print(f"\nImgGen: Clamped Mode (For Shared Use). Step counts and resolution are clamped to {reslimit}x{reslimit}.")

    biggest = max(width,height)
    if biggest > reslimit:
        scaler = biggest / reslimit
        width = int(width / scaler)
        height = int(height / scaler)
        width = width - (width%64)
        height = height - (height%64)

    inputs = sd_generation_inputs()
    inputs.prompt = prompt.encode("UTF-8")
    inputs.negative_prompt = negative_prompt.encode("UTF-8")
    inputs.init_images = init_images.encode("UTF-8")
    inputs.cfg_scale = cfg_scale
    inputs.denoising_strength = denoising_strength
    inputs.sample_steps = sample_steps
    inputs.width = width
    inputs.height = height
    inputs.seed = seed
    inputs.sample_method = sample_method.lower().encode("UTF-8")
    inputs.quiet = is_quiet
    inputs.clip_skip = clip_skip
    ret = handle.sd_generate(inputs)
    outstr = ""
    if ret.status==1:
        outstr = ret.data.decode("UTF-8","ignore")
    return outstr


def whisper_load_model(model_filename):
    global args
    inputs = whisper_load_model_inputs()
    inputs.debugmode = args.debugmode
    inputs.executable_path = (getdirpath()+"/").encode("UTF-8")
    inputs.model_filename = model_filename.encode("UTF-8")
    inputs = set_backend_props(inputs)
    ret = handle.whisper_load_model(inputs)
    return ret

def whisper_generate(genparams):
    global args
    is_quiet = True if (args.quiet or args.debugmode == -1) else False
    prompt = genparams.get("prompt", "")
    audio_data = genparams.get("audio_data", "")
    if audio_data.startswith("data:audio"):
        audio_data = audio_data.split(",", 1)[1]
    inputs = whisper_generation_inputs()
    inputs.prompt = prompt.encode("UTF-8")
    inputs.audio_data = audio_data.encode("UTF-8")
    inputs.quiet = is_quiet
    ret = handle.whisper_generate(inputs)
    outstr = ""
    if ret.status==1:
        outstr = ret.data.decode("UTF-8","ignore")
    return outstr

def tokenize_ids(countprompt,tcaddspecial):
    rawcountdata = handle.token_count(countprompt.encode("UTF-8"),tcaddspecial)
    countlimit = rawcountdata.count if (rawcountdata.count>=0 and rawcountdata.count<50000) else 0
    # the above protects the server in case the count limit got corrupted
    countdata = [rawcountdata.ids[i] for i in range(countlimit)]
    return countdata

def detokenize_ids(tokids):
    tokidslen = len(tokids)
    detokstr = ""
    if tokidslen > 0 and tokidslen < 65536:
        inputs = token_count_outputs()
        inputs.count = tokidslen
        inputs.ids = (ctypes.c_int * tokidslen)()
        for i, cid in enumerate(tokids):
            inputs.ids[i] = cid
        detok = handle.detokenize(inputs)
        detokstr = ctypes.string_at(detok).decode("UTF-8","ignore")
    return detokstr

#################################################################
### A hacky simple HTTP server simulating a kobold api by Concedo
### we are intentionally NOT using flask, because we want MINIMAL dependencies
#################################################################

# Used to parse json for openai tool calls
def extract_json_from_string(input_string):
    parsed_json = None
    try: # First check if model exported perfect json
        parsed_json = json.loads(input_string)
        return parsed_json
    except Exception as e:
        pass
    try: # Next check if all we need is to add brackets to make it perfect json
        parsed_json = json.loads(f"[{input_string}]")
        return parsed_json
    except Exception as e:
        pass
    try:
        # Now use regular expression to match JSON objects or arrays in case part is valid json and part is not
        json_pattern = r'(\{.*?\}|\[.*?\])'  # was json_pattern = r'(\{.*\}|\[.*\])'
        potential_jsons = re.findall(json_pattern, input_string, re.DOTALL)
        for potential_json in potential_jsons:
            try:
                parsed_json = json.loads(potential_json)
                return parsed_json
            except Exception as e:
                continue
    except Exception as e:
        pass
    return []

def parse_last_logprobs(lastlogprobs):
    if not lastlogprobs:
        return None
    logprobsdict = {}
    logprobsdict['content'] = []
    logprobsdict['tokens'] = []
    logprobsdict['token_logprobs'] = []
    logprobsdict['top_logprobs'] = []
    logprobsdict['text_offset'] = []
    text_offset_counter = 0
    for i in range(lastlogprobs.count):
        lp_content_item = {}
        logprob_item = lastlogprobs.logprob_items[i]
        toptoken = ctypes.string_at(logprob_item.selected_token).decode("UTF-8","ignore")
        logprobsdict['tokens'].append(toptoken)
        lp_content_item['token'] = toptoken
        logprobsdict['token_logprobs'].append(logprob_item.selected_logprob)
        lp_content_item['logprob'] = logprob_item.selected_logprob
        lp_content_item['bytes'] = list(toptoken.encode('utf-8'))
        lp_content_item['top_logprobs'] = []
        logprobsdict['text_offset'].append(text_offset_counter)
        text_offset_counter += len(toptoken)
        tops = {}
        for j in range(min(logprob_item.option_count,logprobs_max)):
            tl_item = {}
            tl_item['logprob'] = logprob_item.logprobs[j]
            tokstr = ctypes.string_at(logprob_item.tokens[j]).decode("UTF-8","ignore")
            tops[tokstr] = logprob_item.logprobs[j]
            tl_item['token'] = tokstr
            tl_item['bytes'] = list(tokstr.encode('utf-8'))
            lp_content_item['top_logprobs'].append(tl_item)
        logprobsdict['top_logprobs'].append(tops)
        logprobsdict['content'].append(lp_content_item)
    return logprobsdict

def transform_genparams(genparams, api_format):
    global chatcompl_adapter
    #api format 1=basic,2=kai,3=oai,4=oai-chat,5=interrogate,6=ollama,7=ollamachat
    #alias all nonstandard alternative names for rep pen.
    rp1 = genparams.get('repeat_penalty', 1.0)
    rp2 = genparams.get('repetition_penalty', 1.0)
    rp3 = genparams.get('rep_pen', 1.0)
    rp_max = max(rp1,rp2,rp3)
    genparams["rep_pen"] = rp_max
    if "use_default_badwordsids" in genparams and not ("ban_eos_token" in genparams):
        genparams["ban_eos_token"] = genparams.get('use_default_badwordsids', False)

    if api_format==1:
        genparams["prompt"] = genparams.get('text', "")
        genparams["top_k"] = int(genparams.get('top_k', 120))
        genparams["max_length"] = genparams.get('max', 200)

    elif api_format==2:
        pass

    elif api_format==3 or api_format==4 or api_format==7:
        default_adapter = {} if chatcompl_adapter is None else chatcompl_adapter
        adapter_obj = genparams.get('adapter', default_adapter)
        default_max_tok = (adapter_obj.get("max_length", 512) if (api_format==4 or api_format==7) else 200)
        genparams["max_length"] = genparams.get('max_tokens', genparams.get('max_completion_tokens', default_max_tok))
        presence_penalty = genparams.get('presence_penalty', genparams.get('frequency_penalty', 0.0))
        genparams["presence_penalty"] = presence_penalty
        # openai allows either a string or a list as a stop sequence
        if isinstance(genparams.get('stop',[]), list):
            genparams["stop_sequence"] = genparams.get('stop', [])
        else:
            genparams["stop_sequence"] = [genparams.get('stop')]

        genparams["sampler_seed"] = tryparseint(genparams.get('seed', -1))
        genparams["mirostat"] = genparams.get('mirostat_mode', 0)

        if api_format==4 or api_format==7: #handle ollama chat here too
            # translate openai chat completion messages format into one big string.
            messages_array = genparams.get('messages', [])
            messages_string = ""
            system_message_start = adapter_obj.get("system_start", "\n### Instruction:\n")
            system_message_end = adapter_obj.get("system_end", "")
            user_message_start = adapter_obj.get("user_start", "\n### Instruction:\n")
            user_message_end = adapter_obj.get("user_end", "")
            assistant_message_start = adapter_obj.get("assistant_start", "\n### Response:\n")
            assistant_message_end = adapter_obj.get("assistant_end", "")
            tools_message_start = adapter_obj.get("tools_start", "")
            tools_message_end = adapter_obj.get("tools_end", "")
            images_added = []

            message_index = 0
            for message in messages_array:
                message_index += 1
                if message['role'] == "system":
                    messages_string += system_message_start
                elif message['role'] == "user":
                    messages_string += user_message_start
                elif message['role'] == "assistant":
                    messages_string += assistant_message_start
                elif message['role'] == "tool":
                    messages_string += tools_message_start

                # content can be a string or an array of objects
                curr_content = message['content']
                if isinstance(curr_content, str):
                        messages_string += curr_content
                elif isinstance(curr_content, list): #is an array
                    for item in curr_content:
                        if item['type']=="text":
                                messages_string += item['text']
                        elif item['type']=="image_url":
                            if item['image_url'] and item['image_url']['url'] and item['image_url']['url'].startswith("data:image"):
                                images_added.append(item['image_url']['url'].split(",", 1)[1])
                # If last message, add any tools calls after message content and before message end token if any
                if message['role'] == "user" and message_index == len(messages_array):
                    # Check if user is passing a openai tools array, if so add to end of prompt before assistant prompt unless tool_choice has been set to None
                    tools_array = genparams.get('tools', [])
                    if tools_array and len(tools_array) > 0 and genparams.get('tool_choice',None) != None:
                        response_array = [{"id": "insert an id for the response", "type": "function", "function": {"name": "insert the name of the function you want to call", "arguments": {"first property key": "first property value", "second property key": "second property value"}}}]
                        json_formatting_instruction = " Use this style of JSON object formatting to give your answer if you think the user is asking you to perform an action: " + json.dumps(response_array, indent=0)
                        tools_string = json.dumps(tools_array, indent=0)
                        messages_string += tools_string
                        specified_function = None
                        if isinstance(genparams.get('tool_choice'), dict):
                             try:
                                specified_function = genparams.get('tool_choice').get('function').get('name')
                                json_formatting_instruction = f"The user is asking you to use the style of this JSON object formatting to complete the parameters for the specific function named {specified_function} in the following format: " + json.dumps([{"id": "insert an id for the response", "type": "function", "function": {"name": f"{specified_function}", "arguments": {"first property key": "first property value", "second property key": "second property value"}}}], indent=0)
                             except Exception as e:
                                # In case of any issues, just revert back to no specified function
                                pass
                        messages_string += json_formatting_instruction

                        # Set temperature low automatically if function calling
                        genparams["temperature"] = 0.2
                        genparams["using_openai_tools"] = True

                        # Set grammar to llamacpp example grammar to force json response (see https://github.com/ggerganov/llama.cpp/blob/master/grammars/json_arr.gbnf)
                        genparams["grammar"] = r"""
root   ::= arr
value  ::= object | array | string | number | ("true" | "false" | "null") ws
arr  ::=
  "[\n" ws (
            value
    (",\n" ws value)*
  )? "]"
object ::=
  "{" ws (
            string ":" ws value
    ("," ws string ":" ws value)*
  )? "}" ws
array  ::=
  "[" ws (
            value
    ("," ws value)*
  )? "]" ws
string ::=
  "\"" (
    [^"\\\x7F\x00-\x1F] |
    "\\" (["\\bfnrt] | "u" [0-9a-fA-F]{4})
  )* "\"" ws
number ::= ("-"? ([0-9] | [1-9] [0-9]{0,15})) ("." [0-9]+)? ([eE] [-+]? [1-9] [0-9]{0,15})? ws
ws ::= | " " | "\n" [ \t]{0,20}
"""
                if message['role'] == "system":
                    messages_string += system_message_end
                elif message['role'] == "user":
                    messages_string += user_message_end
                elif message['role'] == "assistant":
                    messages_string += assistant_message_end
                elif message['role'] == "tool":
                    messages_string += tools_message_end

            messages_string += assistant_message_start
            genparams["prompt"] = messages_string
            if len(images_added)>0:
                genparams["images"] = images_added
            if len(genparams.get('stop_sequence', []))==0: #only set stop seq if it wont overwrite existing
                genparams["stop_sequence"] = [user_message_start.strip(),assistant_message_start.strip()]
            else:
                genparams["stop_sequence"].append(user_message_start.strip())
                genparams["stop_sequence"].append(assistant_message_start.strip())
            genparams["trim_stop"] = True


    elif api_format==5:
        firstimg = genparams.get('image', "")
        genparams["images"] = [firstimg]
        genparams["max_length"] = 42
        adapter_obj = {} if chatcompl_adapter is None else chatcompl_adapter
        user_message_start = adapter_obj.get("user_start", "### Instruction:")
        assistant_message_start = adapter_obj.get("assistant_start", "### Response:")
        genparams["prompt"] = f"{user_message_start} In one sentence, write a descriptive caption for this image.\n{assistant_message_start}"

    elif api_format==6:
        detokstr = ""
        tokids = genparams.get('context', [])
        adapter_obj = {} if chatcompl_adapter is None else chatcompl_adapter
        user_message_start = adapter_obj.get("user_start", "\n\n### Instruction:\n")
        assistant_message_start = adapter_obj.get("assistant_start", "\n\n### Response:\n")
        try:
            detokstr = detokenize_ids(tokids)
        except Exception as e:
            utfprint("Ollama Context Error: " + str(e))
        ollamasysprompt = genparams.get('system', "")
        ollamabodyprompt = f"{detokstr}{user_message_start}{genparams.get('prompt', '')}{assistant_message_start}"
        genparams["stop_sequence"] = genparams.get('stop', [])
        genparams["stop_sequence"].append(user_message_start.strip())
        genparams["stop_sequence"].append(assistant_message_start.strip())
        genparams["trim_stop"] = True
        genparams["ollamasysprompt"] = ollamasysprompt
        genparams["ollamabodyprompt"] = ollamabodyprompt
        genparams["prompt"] = ollamasysprompt + ollamabodyprompt

    return genparams

class ServerRequestHandler(http.server.SimpleHTTPRequestHandler):
    sys_version = ""
    server_version = "ConcedoLlamaForKoboldServer"

    def __init__(self, addr, port):
        self.addr = addr
        self.port = port

    def __call__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def log_message(self, format, *args):
        global showdebug
        if showdebug:
            super().log_message(format, *args)
        pass

    def extract_b64string_from_file_upload(self, body):
        try:
            if 'content-type' in self.headers and self.headers['content-type']:
                boundary = self.headers['content-type'].split("=")[1].encode()
                if boundary:
                    fparts = body.split(boundary)
                    for fpart in fparts:
                        detected_upload_filename = re.findall(r'Content-Disposition.*name="file"; filename="(.*)"', fpart.decode('utf-8',errors='ignore'))
                        if detected_upload_filename and len(detected_upload_filename)>0:
                            utfprint(f"Detected uploaded file: {detected_upload_filename[0]}")
                            file_content_start = fpart.find(b'\r\n\r\n') + 4  # Position after headers
                            file_content_end = fpart.rfind(b'\r\n')  # Ending boundary
                            if file_content_start != -1 and file_content_end != -1:
                                file_data = fpart[file_content_start:file_content_end]
                                file_data_base64 = base64.b64encode(file_data).decode('utf-8',"ignore")
                                base64_string = f"data:audio/wav;base64,{file_data_base64}"
                                return base64_string
            print("Uploaded file not found.")
            return None
        except Exception as e:
            print(f"File Upload Process Error: {e}")
            return None

    async def generate_text(self, genparams, api_format, stream_flag):
        global friendlymodelname, chatcompl_adapter, currfinishreason
        is_quiet = args.quiet
        currfinishreason = "null"

        def run_blocking():  # api format 1=basic,2=kai,3=oai,4=oai-chat
            # flag instance as non-idle for a while
            washordereq = genparams.get('genkey', '').startswith('HORDEREQ_')
            if not washordereq:
                global last_non_horde_req_time
                last_non_horde_req_time = time.time()

            return generate(genparams=genparams,is_quiet=is_quiet,stream_flag=stream_flag)

        genout = {"text": "", "status": -1, "stopreason": -1, "prompt_tokens":0, "completion_tokens": 0, "total_tokens": 0}
        if stream_flag:
            loop = asyncio.get_event_loop()
            executor = ThreadPoolExecutor()
            genout = await loop.run_in_executor(executor, run_blocking)
        else:
            genout = run_blocking()

        recvtxt = genout['text']
        prompttokens = genout['prompt_tokens']
        comptokens = genout['completion_tokens']
        currfinishreason = ("length" if (genout['stopreason'] != 1) else "stop")

        # grab logprobs if not streaming
        logprobsdict = None
        if not stream_flag and ("logprobs" in genparams and genparams["logprobs"]):
            lastlogprobs = handle.last_logprobs()
            logprobsdict = parse_last_logprobs(lastlogprobs)

        # flag instance as non-idle for a while
        washordereq = genparams.get('genkey', '').startswith('HORDEREQ_')
        if not washordereq:
            global last_non_horde_req_time
            last_non_horde_req_time = time.time()

        if (args.debugmode != -1 and not is_quiet) or args.debugmode >= 1:
            utfprint("\nOutput: " + recvtxt)

        if api_format == 1:
            res = {"data": {"seqs": [recvtxt]}}
        elif api_format == 3:
            res = {"id": "cmpl-A1", "object": "text_completion", "created": int(time.time()), "model": friendlymodelname,
                   "usage": {"prompt_tokens": prompttokens, "completion_tokens": comptokens, "total_tokens": (prompttokens+comptokens)},
                   "choices": [{"text": recvtxt, "index": 0, "finish_reason": currfinishreason, "logprobs":logprobsdict}]}
        elif api_format == 4:
            using_openai_tools = genparams.get('using_openai_tools', False)
            tool_calls = []
            if using_openai_tools:
                tool_calls = extract_json_from_string(recvtxt)
                if tool_calls and len(tool_calls)>0:
                    recvtxt = None
            res = {"id": "chatcmpl-A1", "object": "chat.completion", "created": int(time.time()), "model": friendlymodelname,
                   "usage": {"prompt_tokens": prompttokens, "completion_tokens": comptokens, "total_tokens": (prompttokens+comptokens)},
                   "choices": [{"index": 0, "message": {"role": "assistant", "content": recvtxt, "tool_calls": tool_calls}, "finish_reason": currfinishreason, "logprobs":logprobsdict}]}
        elif api_format == 5:
            res = {"caption": end_trim_to_sentence(recvtxt)}
        elif api_format == 6:
            oldprompt = genparams.get('ollamabodyprompt', "")
            tokarr = tokenize_ids(oldprompt+recvtxt,False)
            res = {"model": friendlymodelname,"created_at": str(datetime.now(timezone.utc).isoformat()),"response":recvtxt,"done": True,"done_reason":currfinishreason,"context": tokarr,"total_duration": 1,"load_duration": 1,"prompt_eval_count": prompttokens,"prompt_eval_duration": 1,"eval_count": comptokens,"eval_duration": 1}
        elif api_format == 7:
            res = {"model": friendlymodelname,"created_at": str(datetime.now(timezone.utc).isoformat()),"message":{"role":"assistant","content":recvtxt},"done": True,"done_reason":currfinishreason,"total_duration": 1,"load_duration": 1,"prompt_eval_count": prompttokens,"prompt_eval_duration": 1,"eval_count": comptokens,"eval_duration": 1}
        else:
            res = {"results": [{"text": recvtxt, "finish_reason": currfinishreason, "logprobs":logprobsdict, "prompt_tokens": prompttokens, "completion_tokens": comptokens}]}

        try:
            return res
        except Exception as e:
            print(f"Generate: Error while generating: {e}")

    async def send_oai_sse_event(self, data):
        if data=="[DONE]":
            self.wfile.write(f'data: {data}'.encode())
        else:
            self.wfile.write(f'data: {data}\n\n'.encode())
        self.wfile.flush()

    async def send_kai_sse_event(self, data):
        self.wfile.write(f'event: message\n'.encode())
        self.wfile.write(f'data: {data}\n\n'.encode())
        self.wfile.flush()

    async def handle_sse_stream(self, genparams, api_format):
        global friendlymodelname, currfinishreason
        self.send_response(200)
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("cache-control", "no-cache")
        self.send_header("connection", "keep-alive")
        self.end_headers(content_type='text/event-stream')

        current_token = 0
        incomplete_token_buffer = bytearray()
        async_sleep_short = 0.02
        await asyncio.sleep(0.35) #anti race condition, prevent check from overtaking generate
        try:
            tokenReserve = "" #keeps fully formed tokens that we cannot send out yet
            while True:
                streamDone = handle.has_finished() #exit next loop on done
                if streamDone:
                    sr = handle.get_last_stop_reason()
                    currfinishreason = ("length" if (sr!=1) else "stop")
                tokenStr = ""
                streamcount = handle.get_stream_count()
                while current_token < streamcount:
                    token = handle.new_token(current_token)

                    if token is None: # Token isnt ready yet, received nullpointer
                        break

                    current_token += 1
                    newbyte = ctypes.string_at(token)
                    incomplete_token_buffer += bytearray(newbyte)
                    tokenSeg = incomplete_token_buffer.decode("UTF-8","ignore")
                    incseq = is_incomplete_utf8_sequence(incomplete_token_buffer)
                    badFragment = (tokenSeg==" " and len(incomplete_token_buffer)>1) or incseq #partial incomplete unicode
                    if tokenSeg!="" and not badFragment:
                        incomplete_token_buffer.clear()
                        tokenStr += tokenSeg

                if tokenStr!="" or streamDone:
                    sseq = genparams.get('stop_sequence', [])
                    trimstop = genparams.get('trim_stop', False)
                    if trimstop and not streamDone and string_contains_or_overlaps_sequence_substring(tokenStr,sseq):
                        tokenReserve += tokenStr
                        await asyncio.sleep(async_sleep_short) #if a stop sequence could trigger soon, do not send output
                    else:
                        if tokenStr!="" or tokenReserve!="":
                            tokenStr = tokenReserve + tokenStr
                            tokenReserve = ""

                            #apply trimming if needed
                            if trimstop:
                                for trim_str in sseq:
                                    sindex = tokenStr.find(trim_str)
                                    if sindex != -1 and trim_str!="":
                                        tokenStr = tokenStr[:sindex]

                        if tokenStr!="" or streamDone:
                            if api_format == 4:  # if oai chat, set format to expected openai streaming response
                                event_str = json.dumps({"id":"koboldcpp","object":"chat.completion.chunk","created":int(time.time()),"model":friendlymodelname,"choices":[{"index":0,"finish_reason":currfinishreason,"delta":{'role':'assistant','content':tokenStr}}]})
                                await self.send_oai_sse_event(event_str)
                            elif api_format == 3:  # non chat completions
                                event_str = json.dumps({"id":"koboldcpp","object":"text_completion","created":int(time.time()),"model":friendlymodelname,"choices":[{"index":0,"finish_reason":currfinishreason,"text":tokenStr}]})
                                await self.send_oai_sse_event(event_str)
                            else:
                                event_str = json.dumps({"token": tokenStr, "finish_reason":currfinishreason})
                                await self.send_kai_sse_event(event_str)
                            tokenStr = ""
                        else:
                            await asyncio.sleep(async_sleep_short)
                else:
                    await asyncio.sleep(async_sleep_short) #this should keep things responsive

                if streamDone:
                    if api_format == 4 or api_format == 3:  # if oai chat, send last [DONE] message consistent with openai format
                        await self.send_oai_sse_event('[DONE]')
                    break
        except Exception as ex:
            print("Token streaming was interrupted or aborted!")
            print(ex)
            handle.abort_generate()
            time.sleep(0.2) #short delay

        # flush buffers, sleep a bit to make sure all data sent, and then force close the connection
        self.wfile.flush()
        await asyncio.sleep(0.1)
        self.close_connection = True
        await asyncio.sleep(0.05)


    async def handle_request(self, raw_genparams, api_format, stream_flag):
        tasks = []

        genparams = transform_genparams(raw_genparams, api_format)

        try:
            if stream_flag:
                tasks.append(self.handle_sse_stream(genparams, api_format))

            generate_task = asyncio.create_task(self.generate_text(genparams, api_format, stream_flag))
            tasks.append(generate_task)

            await asyncio.gather(*tasks)
            generate_result = generate_task.result()
            return generate_result
        except (BrokenPipeError, ConnectionAbortedError) as cae: # attempt to abort if connection lost
            print("An ongoing connection was aborted or interrupted!")
            print(cae)
            handle.abort_generate()
            time.sleep(0.2) #short delay
        except Exception as e:
            print(e)

    def get_multiplayer_idle_state(self,userid):
        if modelbusy.locked():
            return False
        for key, value in multiplayer_lastactive.items():
            if key!=userid and time.time()-value<6: #6s to idle
                return False
        return True

    def secure_endpoint(self): #returns false if auth fails. caller should exit
        #handle password stuff
        if password and password !="":
            auth_header = None
            auth_ok = False
            if 'Authorization' in self.headers:
                auth_header = self.headers['Authorization']
            elif 'authorization' in self.headers:
                auth_header = self.headers['authorization']
            if auth_header != None and auth_header.startswith('Bearer '):
                token = auth_header[len('Bearer '):].strip()
                if token==password:
                    auth_ok = True
            if auth_ok==False:
                self.send_response(401)
                self.end_headers(content_type='application/json')
                self.wfile.write(json.dumps({"detail": {
                        "error": "Unauthorized",
                        "msg": "Authentication key is missing or invalid.",
                        "type": "unauthorized",
                    }}).encode())
                return False
        return True

    def noscript_webui(self):
        global modelbusy, sslvalid
        import html
        import urllib.parse as urlparse
        parsed_url = urlparse.urlparse(self.path)
        parsed_dict = urlparse.parse_qs(parsed_url.query)
        reply = ""
        status = str(parsed_dict['status'][0]) if 'status' in parsed_dict else "Ready To Generate"
        prompt = str(parsed_dict['prompt'][0]) if 'prompt' in parsed_dict else ""
        max_length = int(parsed_dict['max_length'][0]) if 'max_length' in parsed_dict else 100
        temperature = float(parsed_dict['temperature'][0]) if 'temperature' in parsed_dict else 0.7
        top_k = int(parsed_dict['top_k'][0]) if 'top_k' in parsed_dict else 100
        top_p = float(parsed_dict['top_p'][0]) if 'top_p' in parsed_dict else 0.9
        rep_pen = float(parsed_dict['rep_pen'][0]) if 'rep_pen' in parsed_dict else 1.0
        ban_eos_token = int(parsed_dict['ban_eos_token'][0]) if 'ban_eos_token' in parsed_dict else 0
        gencommand = (parsed_dict['generate'][0] if 'generate' in parsed_dict else "")=="Generate"

        if modelbusy.locked():
            status = "Model is currently busy, try again later."
        elif gencommand:
            if prompt=="" or max_length<=0:
                status = "Need a valid prompt and length to generate."
            else:
                if max_length>512:
                    max_length = 512
                httpsaffix = ("https" if sslvalid else "http")
                epurl = f"{httpsaffix}://localhost:{args.port}"
                if args.host!="":
                    epurl = f"{httpsaffix}://{args.host}:{args.port}"
                gen_payload = {"prompt": prompt,"max_length": max_length,"temperature": temperature,"prompt": prompt,"top_k": top_k,"top_p": top_p,"rep_pen": rep_pen,"ban_eos_token":ban_eos_token}
                respjson = make_url_request(f'{epurl}/api/v1/generate', gen_payload)
                reply = html.escape(respjson["results"][0]["text"])
                status = "Generation Completed"

            if "generate" in parsed_dict:
                del parsed_dict["generate"]
            parsed_dict["prompt"] = prompt + reply
            parsed_dict["status"] = status
            updated_query_string = urlparse.urlencode(parsed_dict, doseq=True)
            updated_path = parsed_url._replace(query=updated_query_string).geturl()
            self.path = updated_path
            self.send_response(302)
            self.send_header("location", self.path)
            self.end_headers(content_type='text/html')
            return

        finalhtml = f'''<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>KoboldCpp NoScript Mode</title></head><body>
<h2>KoboldCpp NoScript Mode</h2>
<div>
<p>KoboldCpp can be used without Javascript enabled, however this is not recommended.
<br>If you have Javascript, please use <a href="/">KoboldAI Lite WebUI</a> instead.</p><hr>
<form action="/noscript">
Enter Prompt:<br>
<textarea name="prompt" cols="60" rows="8" wrap="soft" placeholder="Enter Prompt Here">{prompt}</textarea>
<hr>
<b>{status}</b><br>
<hr>
<label>Gen. Amount</label> <input type="text" size="4" value="{max_length}" name="max_length"><br>
<label>Temperature</label> <input type="text" size="4" value="{temperature}" name="temperature"><br>
<label>Top-K</label> <input type="text" size="4" value="{top_k}" name="top_k"><br>
<label>Top-P</label> <input type="text" size="4" value="{top_p}" name="top_p"><br>
<label>Rep. Pen</label> <input type="text" size="4" value="{rep_pen}" name="rep_pen"><br>
<label>Prevent EOS</label> <input type="checkbox" name="ban_eos_token" value="1" {"checked" if ban_eos_token else ""}><br>
<input type="submit" name="generate" value="Generate"> (Please be patient)
</form>
<form action="/noscript">
<input type="submit" value="Reset">
</form>
</div>
</body></html>'''
        finalhtml = finalhtml.encode('utf-8')
        self.send_response(200)
        self.send_header('content-length', str(len(finalhtml)))
        self.end_headers(content_type='text/html')
        self.wfile.write(finalhtml)

    def do_GET(self):
        global embedded_kailite, embedded_kcpp_docs, embedded_kcpp_sdui
        global has_multiplayer, multiplayer_turn_major, multiplayer_turn_minor, multiplayer_story_data_compressed, multiplayer_dataformat, multiplayer_lastactive, maxctx, maxhordelen, friendlymodelname, lastgeneratedcomfyimg, KcppVersion, totalgens, preloaded_story, exitcounter, currentusergenkey, friendlysdmodelname, fullsdmodelpath, mmprojpath, password, fullwhispermodelpath
        self.path = self.path.rstrip('/')
        response_body = None
        content_type = 'application/json'

        if self.path in ["", "/?"] or self.path.startswith(('/?','?')): #it's possible for the root url to have ?params without /
            content_type = 'text/html'
            if embedded_kailite is None:
                response_body = (f"Embedded KoboldAI Lite is not found.<br>You will have to connect via the main KoboldAI client, or <a href='https://lite.koboldai.net?local=1&port={self.port}'>use this URL</a> to connect.").encode()
            else:
                response_body = embedded_kailite

        elif self.path in ["/noscript", "/noscript?"] or self.path.startswith(('/noscript?','noscript?')): #it's possible for the root url to have ?params without /
            self.noscript_webui()
            return

        elif self.path.endswith(('/manifest.json')):
            response_body = (json.dumps({"name":"KoboldAI Lite","short_name":"KoboldAI Lite","description":"Progressive Web App for KoboldAI Lite","start_url":"./","scope":".","display":"standalone","background_color":"#303030","theme_color":"#337ab7","orientation":"portrait-primary","icons":[{"src":"data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAJYAAACWCAMAAAAL34HQAAAAAXNSR0IB2cksfwAAAAlwSFlzAAALEwAACxMBAJqcGAAAAJZQTFRFAAAA+3F0nlRTBAMD+9Oq9HR2DwoKHBIT+Pj3s1dY5WttlUtL8MOhMhsaSygngENC8YB+ZjY1JyEmOTI3AAAA0l5gzUlKTENIdG3SAgEBAQEAAgIBAQAAAQEBraup8KCWY1tarZqQ3tvdamOriYaG3nR0kGRf1ayUdWxto3909WRovby9x673UEp1x4R9lIfPs57jv6znVipSqwAAADJ0Uk5TAP///f////7///////7+/v/+//8G/////35O1yCv///////////+///////////////GhbwlAAAU9klEQVR4nO2ca3ejug6GT6Dg4R5wCW1zgzTckkna/v8/d17JQEhCLjNN96fRWjO7003MY1mWJdnO//73T/7JP/knD5Xn2VzX9enr7PnKQ2/zqa7PZ/8V0+x1Ti8krvkVrhk/NJ3O5/PXn2Z7nr29KiYv9IWuX37h7HVq+qGu8F/frqn1+1Cvrxg9M/KE7juOb+rTC+97Zqog1IXve3hs/np9wL8F9fYKRZnCD4LQ80Jr4pO6ht4GKh3gofDCQgt8YdKAv739xFg2UJ4fBlq913wvmEzEBbMnKs8JPL/Y15oT+h6B0bMPp3ruNOU4jpXnhfScWBOD7yIq0wJVneeW4wSQUJCRPZwLtgJNJSGoNIiV74PIn8TBIBeeFdrEk8U+t+hpkIVsY/qDJyVRiaij0hyMTiLCzSTwdHIBx4JnAzvwgv1+r6nHgzAMPTWQj7T8N+jK9EIeQX6PZu2LyIs3EzU6JyJCOyfDygut0VZAhm/Cp0zfHoml64kQxEVkPIxW4QvLJi78DxYfAwXBv8PYiEVS75shBJYDZYnQgm5fH4plLtKo4eKBtCwtFI69wTiGpEPIZDJhhDC0RrYDLEVFH4DJQ9nx5PFY5bKgDve4QjOwR5tBGdmBGYC80NqJaHrow+Thg2hmy6Xl66YM6EXggrYIyzBGQ2IHgrD4WTgwXY80wyCsRypLYY3zOFCGryz/CpYBrFCZlcM+K7RyKPYHsOrl2DBszRfCbyw/NB3COhfC0kQCkyIouHhfi/HLTez8DNZolMN5i8j3Q6B5whoeQWAZsQc3B0E3vMDK6cENed+fwSKFof/Ck74v/PwyluGLKCJv4YWa3ajw8VhTsyrH3PjIyAFG7/MDYzTMRc8FHju0UMsZ6Wew5nqqsLjjhu1gFGHFlyyehlvDEDo2f+LHsKaMNVLa4XfkeT4eqXcOYtEDRsvNfz3atp5BpQf52Oi9daT0dkXUiBvGeLl0WZbj4YDjb6koqIHjGfMrIOOG5zqWeoKZnlhct0wfx0VUWGUVUdPve7HGywap4dpjAbuRx90pFGp5xf7QaWq/Gc9bWMa4TwUstywuJgB/RgXfENVHrTNXO0hXNWaMTz4GqZEwfZtrhkjLO6N6emrN/zrWeHnaHUjGXN+iIrvysnMqGsbblnWOpQzsu1ygMgepnp6Wd2ENdYi5vjMfSVfndtVgjf8Si7hq+R0ueNGoGKZ6gnO8STWMRWC1/0c50OytL1eoSF2jmx5iPPxROL4CUf3Ru64VT56p8tHIdAovWnUOuv3hMVjwX0JvylFKrtSknmf8oGlSokl/grJpJMuyksjcg6W53cp9F1bXP/4ZTTrqTUquFgJAZfoBJVYIios0DPdP6FbCqR/Fc7Vb+n72V1hlVaOL+yJNZJLgZ1ofQ6coCpXHhebllIhcJ6isOI4ncV6S1In00BeT9Wx6abb2/EZhf4Ll7kNZlzWFtaYpTETdYVDzC5Y23hVPHORGl6xrNseS7Fg2clKb1lg3S6VK5c02iU/WacvF6/WdWGUo0rriOpfOI0a1n2JPVrGktDJ2sFLOh9XFpbJAi8l/20RVJ2hHyCRNoXqhWpNVEvn1Aes6l8KieCYp0kj1MIJQYybSbuKiYDe3Qqhr2GMgMDYDzYo5tFyCysPoRcl6QbJOo4YrTQTb1/1YTJUIUjraS6uq7SUGVq1iRuwgmRxUFy00vkZYI8bKqHciBVKWrSGpUCMALi9gD3EnFvoXZXgr9IT21pjUqpcAI7fIjoYqUuagujCGwrGANWJtZZIYSFcYNtHYPE9l4ipbrDtsK5NRRbqKMIxmJGkmkvobfdHiymE+1u+hIj7GMCqgLZvetdyn0HgSRRJIrcE3YiapCN27sdzUS1JqQ5AZ0LTGZJQVuNgm9ktOxO2Aal8D+cfrFBagaXFOMRQtDrq5TqITJDUfZSIQVtyJVfsyPZ7PbPipsgqRqADciMPBIhN5h6A1rXEdUhupNJvJo7P6o6byF6WiKu+0LTeVUg71Lam4dVHnRDWyHS4VnloXRVYOjyE1FzCA0hUmjwTUbrerdolo1CWzO2diBiqzUXKa7iRMPeJ5KCQ3b/qxwc3EtP0wP8UiV6phDG3yI7HfKRyealFF0e795eXl4/Njp7hSsb4TK41IWeQadh9fX2hAkk+Wh4qrqXHZZ2THVB4+MfpnBMeBFiCBz3M7P9RphcRcTEQCqJf394+vD27QTEVaLu8IA59cP6FPmET1+fn79+/P90hki3Vy4Apj1dBmEtIKdKQvxFZwWoEfhj6km3xmgrlcRZJ09bKLkq/fHzwknkTecU90WotEsnmihXf5xVwmnGGWduMhgngMMTYbhxbs2dkY1oUn2jhDUZE3bZX1Ik2Z/f69pjEx06i4R1tu4El2yzvqlViTvj4iGoEsbScn/AXXqYOJE9GGQh8Ly2Gxz6nYd+SheOWR0Y7HMNKjCr2tIp6kxf52kjF2fZ7NJkzzPYGd8jDCMBdH+uJ3+U5MozifH2PBWMaGbQUHa9cVVdaMIbBMjOLvj5RdfRHfTvbHpVdF3RBCaR88iqLidpO+I/Mx22KEhq+vp1iuixGmmlozipFapSuBvn58fABLj6jdNX4Q1T6/neyP3YqwWNs0h82PLx5F1d+D3ZteaMHTxwGwjtZrZBPkIcEFMNo2wtzhPm1h8buXj9Vq9blDmPOu1GXq63LMWNez6icXKjElfMvLjjr7zqOYyPV2uyUu7r/wfK5jsoc4NnmqyiQcZoyMcY6h9LCg4rPb1aoij/MLspBQEtr9omU2ze7D8llZn1+fO9FifaVy8evXyt1u15LsPYTnGimqs4iealjS5fCHKnl7KGr1iyWFaX3iv6sFjDahdrdQl6zvwYKDQCjEvVpVHVZFWPSrbVZVNHXo2RgdOPfyMwQ2cACuSkuNZbnY/jpgfXx+QWsmz6UVAPGTcxdWgMhdKXtFJslYK4zBr4YLlr/nAM/i7cbzQPCZudal4hofY8E4vthmI8L6tcKsD+07TL7EvKZerVYLDm/f+eOdAKvcU6pia545nb8N5Yq0G4+Qq+TFbryvj7FefvexECxhzbjDQUSMBW2/cxhxggW9l3mzHEJVl08J6F5B/gtKTfu2BbejtCVVu1tp+tYdWHtyceS0Pl6SIaztOsuNTYw1eHqJqjF8rCrE5UTrPtb7+yeFbWTy/OtURBpee8O2DAtLC3189/GxI/9EttXHWic1sMgxXC8QIkYNuJTseGmDRX6rxWIHodQlgttYdkA73Nyrj7TF6qlrVXkFYYnzKXiGlZLNjx0RfTU9Yif9/kKJnuCp9PvXCrB3YMWhXiU7hbUzG6we1yLxNGO0QU59EwuDSG9zTNGM4lZyDPie8uIDL//58S63iyQwjFslrtgX6zThT7+rxQcfxkKWNWRrz7dGjDW9CwsRv2kmzYcbLMSVHAKg4Z3Yrmrt1jYGaStdpFLFHztKx7C00vJYqVm+ShGo58Dyb2IhdcPKaFG6KRoXofpLXPL98xNU7xLEJe183cCyrWxRSRWtvSdN6I1QpBkHrGaY0PlmchNrrstsObbo5ACWY/XpLGma21EowR1f//rlGrexDKxhaxm9v3QfV3rbtpMJ1oqI5h6sZL8cI3jWHKHLVtdqGMlC3mm2k7J+LUeGcTPiGiMESSOlrlbeo2aOrxLT9HzPn9yLxQkSls5afX4tlX3whMQQygxtLlkdt9RVLrDCR7s+1U4s2imu+zWiFcsK78DKEElR+u0g5MraBqK01dcOoTh+1Wz7dFZ/2D4/HsVydcwFE6saZSGqCegjd9kWtGVvNgbNRUp8mqUrgVtkkUjR0CxvxbY7hobNEsf0t9psbTHzcstcnXlK2VKlCC4C8kV3Yfm1HU8myHEF1bcSZfarLdVtIBGiw9Vqnaax2sK0LTq84vclDMPAQXrOfOOiyjh8QBYLiaKk9YaVYHu378WyYmsyAZXkqD5K1xnC1NV2XaVJktK/KClO8xFiby1oT7L1SsZU6PNAR1XYzbjwqSPbNZUU8afiAID+HQEK/XHiOL7tTue6pxFW4PuFsadyBRVFkrSq67qq0opKeZHwgn0eW07IaaVoTiOxqLNJgtNNzw8dqw4FlY0W2XpdrdEnzi2gepMOKCGg8amufZeXj6kkHThIuOBWvX42ZypVIPi2+f8QE96tjpqRFEVBR5BCUiIVxujoC37Egi2VZUZRU5tC12rDsEKfyt/3YKXxZjKxoLERnxHwOiYlPnLz3OIqheklaaFdECdNVL3CD6Aws9exJi/kGgyV5e/DCgiLZYPVI6CqDw0VOhwGRY3U27aolG1GSeBcYtLaU25ScK1b46M2B61HYUFlLZpcbMd3BDZhHCsqmkyx09V8hE9nZQysvzQTyKSvQ7WnAj06xTSJY0sL2+mh8tXRRr2IC1vXj0fzacNGWRNKItCaow4gYWIRJx3yA+E9TC2YLwQdtIFDx9SLInIi3MNmVLgOeJnrefZGhRvLiLtBVP678ZLkHbXAA1R4N1QHBk8Aj2LRuTzL4g4a3XswQS5uRTVng8kUW3VtNt36YvAOT65FYgDKGpTeA0XgYebl/RNe1G47KhOH0/xBdVHaowszhPsebVptbbr1mLKhmJJRGZzwqDWn1adSKi9FfTQMPbh6mSWtby0V5lgA83qbDQwkUemOz1g0R2yKIiZxt+jyKml6QZ8pjg8Hb46XaKxLEPjc7vHU95w2QOPxizuszWZDZyyn0/P9ApgVHHzut5XMUaO0uNMXsjkv6caPiqx5t1afHsI7xBQNGf7CnLTaQ3vsGajbBIUPsLoG7gXQbrA/sQ3f7x2s467wGyiXcMKwdZ4wWfskirkU13dgZPp5c/5L8YzU6VC0PjZIXULQ3vCRwmjfVYP75FSklbivLcPC0nKAGmQ4sPT/ATtrwLpDe5u2w+oJWMImxFwS59VAnzQce31twWzjTfdZdZqboY4Q7CE5wjaMhstqueBIDy2rblieFyLEO62dBlQJ1Ly+bZHHOmna4qnQqKMJ/njOdRKztHStnSmPpcXtL+yTvmGqh54PA5tOj7FSiuED0cfqf05ZSBPcNcxx3zedCXvNvPVRtrL8gxp7r1HxLNIt/7QAPqX8cDn2zWDYbIxY61PdZOrYYrsda24hHmpeYdl0z+Vkd2U+FZW7HHumMzyjqLOW1Q7KvVCss/zoM0NVMYU1ov2vE1fPRyWXe0FVqwvKsuLWYO+F4mMO3cAZNk2armvnWJZ/vhVF6bRbmGE8hEWW8edUnHtgAeVxNBoXZg28QP1mow1kGq80iurw9ABWjmWmXWfUlHS6g/MXxKFoGQG2w1unzXpASdsFrM1gmQujmJTCtAbrCv1FpfFBIWUT8nIsSLccENJytGF1VYGhFLfFmoQDh6dmtIOuC2u4fNxrSs10WuEomO4t3ScjSGmgp8INK+43Ndy6wVWu85iLdoX15Pr+Eh9nbhy2E/q06+8Pc1EgLHzZUA8dYO97bcZCzDU/o+IQQucthaMY4Ky1ztxDjzadeSt5AMtDaoGQ0TnFOlQIjpVlTyiiP8d6fnvV9WzZj5+GogK7w0JkR7mgP4hV0GaWaFVp2VfbJGGDHzzN8gYsd3mEda76AxamGiX33qDRO5TvHBKR4RWtx7ghZV04+6Pr63LZFYiGJ03fZwVkXRewfK8f8x9hdSYyHrdv2Uyci3dt4CMkbfn05ZTLOPKkBdzEsG1Bl/182+rHC82yOh4v23cZV5TFB7hq92nZl1Mu49618FiGsPpvsR39yik8qCsjrPG+xnIWpLQtZfwMlpEHVCyo93s6imddThRZXWYkm1IQSXXG9QAsRcXJHdXxSKisffkkpbou3Qn8fuWenMb9S6z4dH7bdEjxznOnsPpXugbdCE2BurtK0Djjv8fqT25F1b7ola5eXy3ZzN7eDikR1iOytYPL+A5WP4s0EFr1LmU8z2Z/cu6a8n+ZHU3Hv8Zqo22uQtOJp29cyaA54JfL3iH0B2DRToR56ZTpH3BlT4f5+C3bitXhUUX1ndsYz90xhNbC/h4LZu7RhbLvU7VcVV1oew6a/w6LSn88+Twnt5jqu1eQ+EsBIhl5YZH/LRalFUxFX4wQPoLqf009TqfqPhVcTrDUhdtOgsMN514SAh+fI9KJ1Hm8q0cL/pDLjCJwUfGkufvbiN/sC7Sle+F5fkPX7ADR/g8F6jAFN5MP/UIBii0SydWcWPOF2b8VcPSPA1533JiKzPlE6HQnwBGPGcBGnunaZJZ6voZ5RCfxRbcvgemQsZR0MyKri7SpvUdJVVUJ1/PDQIiifHpyA/HgO/tzs9qWqaCv8qBNMxY6jJfSHQ0WdRPLdcuyoKwn5W2nNagoUvBqvtXx8JvCwFo9ZSneIfkg5GKx3WZCF/XQxZQ6MelUIm1w6qKqpJc0FxK0x1/JXaPlskjSdSLpHNwK7xRYmQZvzNQ+sOiQ1tb0yrIumvtebv14LNXhvftUeOmCz7lsTb0YxnILYNF+5gLZweFCjbuPHn85vm29EFKdodpy6D8omeBt1tVaT34Ya9GNkGxOfSzAegnL4+Nfq1Sv+ljlD2K5qeDzFVCFNzyGMMJE0PGerTzS549iPdURHyfZpmYwqCzMhm1hkka3QvTBXTe6lAz+NVa56lSh1LWQglRR1uRQy7JxWvCo6/V2tTCTLfRppsc3hf3HfpcTsPCWtvXaoyHKoAoXVJJvo6RKkoQOO1TbVYRHFkmUPR1hye9FpQNYi9VBXYUpF9vK9F11AbKfWNENQiRy20okGf4cX2AupflgLORm2w7M9c0klV7huntJ3xc1nx5kTrulmKsSa448UhYUO3yX5++xKK/lwzXNG3zEBrIkKqqVPfdFXU5drOkOVHMhkbuSJfqjvyaMj6SaQq6/yBspsxfJUznc/WcsCnKxlknZ0xTdGXrMvfgjLiTcdPahgrEzV11nZXIh1KQEIKG1uoWqFNTg6eBvCoPRbZ31glwT3e+7lMJwYpJirWY7rwFFO6s/9c1g6hvUWGWLLa3HV84hz2FZ25WbZQXf+LpwjvpB8tx8tRsC86ySp3cBzrjwDB0doun50986NyN30HioaylMV5T6D5hInp9ns7fpLarmBMOczPwnvwbvjOzWt+7N3t5eZ7P/Dqp9662hAdd/QvJP/skfyP8BnWh46M1E/qoAAAAASUVORK5CYII=","type":"image/png","sizes":"150x150"}]}).encode())

        elif self.path.endswith(('/api/v1/model', '/api/latest/model')):
            auth_ok = True
            if password and password !="":
                auth_header = None
                auth_ok = False
                if 'Authorization' in self.headers:
                    auth_header = self.headers['Authorization']
                elif 'authorization' in self.headers:
                    auth_header = self.headers['authorization']
                if auth_header != None and auth_header.startswith('Bearer '):
                    token = auth_header[len('Bearer '):].strip()
                    if token==password:
                        auth_ok = True
            response_body = (json.dumps({'result': (friendlymodelname if auth_ok else "koboldcpp/protected-model") }).encode())

        elif self.path.endswith(('/api/v1/config/max_length', '/api/latest/config/max_length')):
            response_body = (json.dumps({"value": maxhordelen}).encode())

        elif self.path.endswith(('/api/v1/config/max_context_length', '/api/latest/config/max_context_length')):
            response_body = (json.dumps({"value": min(maxctx,maxhordectx)}).encode())

        elif self.path.endswith(('/api/v1/config/soft_prompt', '/api/latest/config/soft_prompt')):
            response_body = (json.dumps({"value":""}).encode())

        elif self.path.endswith(('/api/v1/config/soft_prompts_list', '/api/latest/config/soft_prompts_list')):
            response_body = (json.dumps({"values": []}).encode())

        elif self.path.endswith(('/api/v1/info/version', '/api/latest/info/version')):
            response_body = (json.dumps({"result":"1.2.5"}).encode())

        elif self.path.endswith(('/api/extra/true_max_context_length')): #do not advertise this to horde
            response_body = (json.dumps({"value": maxctx}).encode())

        elif self.path.endswith(('/api/extra/version')):
            has_txt2img = not (friendlysdmodelname=="inactive" or fullsdmodelpath=="")
            has_vision = (mmprojpath!="")
            has_password = (password!="")
            has_whisper = (fullwhispermodelpath!="")
            response_body = (json.dumps({"result":"KoboldCpp","version":KcppVersion, "protected":has_password ,"txt2img":has_txt2img,"vision":has_vision,"transcribe":has_whisper,"multiplayer":has_multiplayer}).encode())

        elif self.path.endswith(('/api/extra/perf')):
            global last_req_time, start_time
            lastp = handle.get_last_process_time()
            laste = handle.get_last_eval_time()
            lastc = handle.get_last_token_count()
            totalgens = handle.get_total_gens()
            totalimggens = handle.get_total_img_gens()
            stopreason = handle.get_last_stop_reason()
            lastseed = handle.get_last_seed()
            uptime = time.time() - start_time
            idletime = time.time() - last_req_time
            is_quiet = True if (args.quiet and args.debugmode != 1) else False
            response_body = (json.dumps({"last_process":lastp,"last_eval":laste,"last_token_count":lastc, "last_seed":lastseed, "total_gens":totalgens, "stop_reason":stopreason, "total_img_gens":totalimggens, "queue":requestsinqueue, "idle":(0 if modelbusy.locked() else 1), "hordeexitcounter":exitcounter, "uptime":uptime, "idletime":idletime, "quiet":is_quiet}).encode())

        elif self.path.endswith('/api/extra/generate/check'):
            if not self.secure_endpoint():
                return
            pendtxtStr = ""
            if requestsinqueue==0 and totalgens>0 and currentusergenkey=="":
                pendtxt = handle.get_pending_output()
                pendtxtStr = ctypes.string_at(pendtxt).decode("UTF-8","ignore")
            response_body = (json.dumps({"results": [{"text": pendtxtStr}]}).encode())

        elif self.path.endswith('/api/extra/last_logprobs'):
            if not self.secure_endpoint():
                return
            logprobsdict = None
            if requestsinqueue==0 and totalgens>0 and currentusergenkey=="":
                lastlogprobs = handle.last_logprobs()
                logprobsdict = parse_last_logprobs(lastlogprobs)
            response_body = (json.dumps({"logprobs":logprobsdict}).encode())

        elif self.path.endswith('/v1/models'):
            response_body = (json.dumps({"object":"list","data":[{"id":friendlymodelname,"object":"model","created":int(time.time()),"owned_by":"koboldcpp","permission":[],"root":"koboldcpp"}]}).encode())

        elif self.path.endswith('/sdapi/v1/sd-models'):
            if friendlysdmodelname=="inactive" or fullsdmodelpath=="":
                response_body = (json.dumps([]).encode())
            else:
                response_body = (json.dumps([{"title":friendlysdmodelname,"model_name":friendlysdmodelname,"hash":"8888888888","sha256":"8888888888888888888888888888888888888888888888888888888888888888","filename":fullsdmodelpath,"config": None}]).encode())
        elif self.path.endswith('/sdapi/v1/options'):
            response_body = (json.dumps({"samples_format":"png","sd_model_checkpoint":friendlysdmodelname}).encode())
        elif self.path.endswith('/sdapi/v1/samplers'):
            if friendlysdmodelname=="inactive" or fullsdmodelpath=="":
                response_body = (json.dumps([]).encode())
            else:
                response_body = (json.dumps([{"name":"Euler a","aliases":["k_euler_a","k_euler_ancestral"],"options":{}},{"name":"Euler","aliases":["k_euler"],"options":{}},{"name":"Heun","aliases":["k_heun"],"options":{}},{"name":"DPM2","aliases":["k_dpm_2"],"options":{}},{"name":"DPM++ 2M","aliases":["k_dpmpp_2m"],"options":{}},{"name":"LCM","aliases":["k_lcm"],"options":{}}]).encode())
        elif self.path.endswith('/sdapi/v1/latent-upscale-modes'):
           response_body = (json.dumps([]).encode())
        elif self.path.endswith('/sdapi/v1/upscalers'):
           response_body = (json.dumps([]).encode())

        elif self.path.endswith(('/api/tags')): #ollama compatible
            response_body = (json.dumps({"models":[{"name":"koboldcpp","model":friendlymodelname,"modified_at":"2024-07-19T15:26:55.6122841+08:00","size":394998579,"digest":"b5dc5e784f2a3ee1582373093acf69a2f4e2ac1710b253a001712b86a61f88bb","details":{"parent_model":"","format":"gguf","family":"koboldcpp","families":["koboldcpp"],"parameter_size":"128M","quantization_level":"Q4_0"}}]}).encode())

        #comfyui compatible
        elif self.path=='/system_stats':
            response_body = (json.dumps({"system":{"os":"posix","ram_total":12345678900,"ram_free":12345678900,"comfyui_version":"v0.3.4-3-g7126ecf","python_version":"3.10.12","pytorch_version":"2.5.1","embedded_python":False,"argv":[]},"devices":[{"name":"koboldcpp","type":"cuda","index":0,"vram_total":12345678900,"vram_free":12345678900,"torch_vram_total":12345678900,"torch_vram_free":12345678900}]}).encode())
        elif self.path=='/object_info':
             response_body = (json.dumps({"KSampler":{"input":{"required":{"model":["MODEL",{"tooltip":""}],"seed":["INT",{"default":0,"min":0,"max":512,"tooltip":""}],"steps":["INT",{"default":20,"min":1,"max":512,"tooltip":""}],"cfg":["FLOAT",{"default":8.0,"min":0.0,"max":100.0,"step":0.1,"round":0.01,"tooltip":"512"}],"sampler_name":[["euler"],{"tooltip":""}],"scheduler":[["normal"],{"tooltip":""}],"positive":["CONDITIONING",{"tooltip":""}],"negative":["CONDITIONING",{"tooltip":""}],"latent_image":["LATENT",{"tooltip":""}],"denoise":["FLOAT",{"default":1.0,"min":0.0,"max":1.0,"step":0.01,"tooltip":""}]}},"input_order":{"required":["model","seed","steps","cfg","sampler_name","scheduler","positive","negative","latent_image","denoise"]},"output":["LATENT"],"output_is_list":[False],"output_name":["LATENT"],"name":"KSampler","display_name":"KSampler","description":"KSampler","python_module":"nodes","category":"sampling","output_node":False,"output_tooltips":[""]},"CheckpointLoaderSimple":{"input":{"required":{"ckpt_name":[[friendlysdmodelname],{"tooltip":""}]}},"input_order":{"required":["ckpt_name"]},"output":["MODEL","CLIP","VAE"],"output_is_list":[False,False,False],"output_name":["MODEL","CLIP","VAE"],"name":"CheckpointLoaderSimple","display_name":"Load","description":"","python_module":"nodes","category":"loaders","output_node":False,"output_tooltips":["","",""]},"CLIPTextEncode":{"input":{"required":{"text":["STRING",{"multiline":True,"dynamicPrompts":True,"tooltip":""}],"clip":["CLIP",{"tooltip":""}]}},"input_order":{"required":["text","clip"]},"output":["CONDITIONING"],"output_is_list":[False],"output_name":["CONDITIONING"],"name":"CLIPTextEncode","display_name":"CLIP","description":"","python_module":"nodes","category":"conditioning","output_node":False,"output_tooltips":[""]},"CLIPSetLastLayer":{"input":{"required":{"clip":["CLIP"],"stop_at_clip_layer":["INT",{"default":-1,"min":-24,"max":-1,"step":1}]}},"input_order":{"required":["clip","stop_at_clip_layer"]},"output":["CLIP"],"output_is_list":[False],"output_name":["CLIP"],"name":"CLIPSetLastLayer","display_name":"CLIPSLL","description":"","python_module":"nodes","category":"conditioning","output_node":False},"VAEDecode":{"input":{"required":{"samples":["LATENT",{"tooltip":""}],"vae":["VAE",{"tooltip":""}]}},"input_order":{"required":["samples","vae"]},"output":["IMAGE"],"output_is_list":[False],"output_name":["IMAGE"],"name":"VAEDecode","display_name":"VAE","description":"","python_module":"nodes","category":"latent","output_node":False,"output_tooltips":[""]},"VAEEncode":{"input":{"required":{"pixels":["IMAGE"],"vae":["VAE"]}},"input_order":{"required":["pixels","vae"]},"output":["LATENT"],"output_is_list":[False],"output_name":["LATENT"],"name":"VAEEncode","display_name":"VAE","description":"","python_module":"nodes","category":"latent","output_node":False},"VAEEncodeForInpaint":{"input":{"required":{"pixels":["IMAGE"],"vae":["VAE"],"mask":["MASK"],"grow_mask_by":["INT",{"default":6,"min":0,"max":64,"step":1}]}},"input_order":{"required":["pixels","vae","mask","grow_mask_by"]},"output":["LATENT"],"output_is_list":[False],"output_name":["LATENT"],"name":"VAEEncodeForInpaint","display_name":"VAE","description":"","python_module":"nodes","category":"latent/inpaint","output_node":False},"VAELoader":{"input":{"required":{"vae_name":[["kcpp_vae"]]}},"input_order":{"required":["vae_name"]},"output":["VAE"],"output_is_list":[False],"output_name":["VAE"],"name":"VAELoader","display_name":"Load VAE","description":"","python_module":"nodes","category":"loaders","output_node":False},"EmptyLatentImage":{"input":{"required":{"width":["INT",{"default":512,"min":16,"max":16384,"step":8,"tooltip":""}],"height":["INT",{"default":512,"min":16,"max":16384,"step":8,"tooltip":""}],"batch_size":["INT",{"default":1,"min":1,"max":1,"tooltip":""}]}},"input_order":{"required":["width","height","batch_size"]},"output":["LATENT"],"output_is_list":[False],"output_name":["LATENT"],"name":"EmptyLatentImage","display_name":"Empty Latent Image","description":"","python_module":"nodes","category":"latent","output_node":False,"output_tooltips":[""]}}).encode())
        elif self.path.endswith('/api/models/checkpoints') or self.path.endswith('/models/checkpoints'): #emulate comfyui, duplication is redundant but added for clarity
            if friendlysdmodelname=="inactive" or fullsdmodelpath=="":
                response_body = (json.dumps([]).encode())
            else:
                response_body = (json.dumps([friendlysdmodelname]).encode())
        elif self.path=='/view' or self.path=='/api/view' or self.path.startswith('/view?') or self.path.startswith('/api/view?'): #emulate comfyui
            content_type = 'image/png'
            response_body = lastgeneratedcomfyimg
        elif self.path=='/history' or self.path=='/api/history' or self.path.startswith('/api/history/') or self.path.startswith('/history/'): #emulate comfyui
            imgdone = (False if lastgeneratedcomfyimg==b'' else True)
            response_body = (json.dumps({"12345678-0000-0000-0000-000000000001":{"prompt":[0,"12345678-0000-0000-0000-000000000001",{"3":{"class_type":"KSampler","inputs":{"cfg":5.0,"denoise":1.0,"latent_image":["5",0],"model":["4",0],"negative":["7",0],"positive":["6",0],"sampler_name":"euler","scheduler":"normal","seed":1,"steps":20}},"4":{"class_type":"CheckpointLoaderSimple","inputs":{"ckpt_name":friendlysdmodelname}},"5":{"class_type":"EmptyLatentImage","inputs":{"batch_size":1,"height":512,"width":512}},"6":{"class_type":"CLIPTextEncode","inputs":{"clip":["4",1],"text":"prompt"}},"7":{"class_type":"CLIPTextEncode","inputs":{"clip":["4",1],"text":""}},"8":{"class_type":"VAEDecode","inputs":{"samples":["3",0],"vae":["4",2]}},"9":{"class_type":"SaveImage","inputs":{"filename_prefix":"kliteimg","images":["8",0]}}},{},["9"]],"outputs":{"9":{"images":[{"filename":"kliteimg_00001_.png","subfolder":"","type":"output"}]}},"status":{"status_str":"success","completed":imgdone,"messages":[["execution_start",{"prompt_id":"12345678-0000-0000-0000-000000000001","timestamp":1}],["execution_cached",{"nodes":[],"prompt_id":"12345678-0000-0000-0000-000000000001","timestamp":1}],["execution_success",{"prompt_id":"12345678-0000-0000-0000-000000000001","timestamp":1}]]},"meta":{"9":{"node_id":"9","display_node":"9","parent_node":None,"real_node_id":"9"}}}}).encode())

        elif self.path.endswith(('/.well-known/serviceinfo')):
            response_body = (json.dumps({"version":"0.2","software":{"name":"KoboldCpp","version":KcppVersion,"repository":"https://github.com/LostRuins/koboldcpp","homepage":"https://github.com/LostRuins/koboldcpp","logo":"https://raw.githubusercontent.com/LostRuins/koboldcpp/refs/heads/concedo/niko.ico"},"api":{"koboldai":{"name":"KoboldAI API","rel_url":"/api","documentation":"https://lite.koboldai.net/koboldcpp_api","version":KcppVersion},"openai":{"name":"OpenAI API","rel_url ":"/v1","documentation":"https://openai.com/documentation/api","version":KcppVersion}}}).encode())

        elif self.path=="/props":
            ctbytes = handle.get_chat_template()
            chat_template = ctypes.string_at(ctbytes).decode("UTF-8","ignore")
            response_body = (json.dumps({
                "chat_template": chat_template,
                "total_slots": 1,
                "default_generation_settings": {
                    "n_ctx": maxctx,
                },
            }).encode())

        elif self.path=="/api" or self.path=="/docs" or self.path.startswith(('/api/?json=','/api?json=','/docs/?json=','/docs?json=')):
            content_type = 'text/html'
            if embedded_kcpp_docs is None:
                response_body = (f"KoboldCpp API is running!\n\nAPI usage reference can be found at the wiki: https://github.com/LostRuins/koboldcpp/wiki").encode()
            else:
                response_body = embedded_kcpp_docs

        elif self.path.startswith(("/sdui")):
            content_type = 'text/html'
            if embedded_kcpp_sdui is None:
                response_body = (f"KoboldCpp API is running, but KCPP SDUI is not loaded").encode()
            else:
                response_body = embedded_kcpp_sdui

        elif self.path=="/v1":
            content_type = 'text/html'
            response_body = (f"KoboldCpp OpenAI compatible endpoint is running!\n\nFor usage reference, see https://platform.openai.com/docs/api-reference").encode()

        elif self.path=="/api/extra/preloadstory":
            if preloaded_story is None:
                response_body = (json.dumps({}).encode())
            else:
                response_body = preloaded_story
        elif self.path.endswith(('/api')) or self.path.endswith(('/api/v1')):
            self.path = "/api"
            self.send_response(302)
            self.send_header("location", self.path)
            self.end_headers(content_type='text/html')
            return None

        if response_body is None:
            self.send_response(404)
            self.end_headers(content_type='text/html')
            rp = 'Error: HTTP Server is running, but this endpoint does not exist. Please check the URL.'
            self.wfile.write(rp.encode())
        else:
            self.send_response(200)
            self.send_header('content-length', str(len(response_body)))
            self.end_headers(content_type=content_type)
            self.wfile.write(response_body)
        return

    def do_POST(self):
        global modelbusy, requestsinqueue, currentusergenkey, totalgens, pendingabortkey, lastgeneratedcomfyimg, multiplayer_turn_major, multiplayer_turn_minor, multiplayer_story_data_compressed, multiplayer_dataformat, multiplayer_lastactive
        contlenstr = self.headers['content-length']
        content_length = 0
        body = None
        if contlenstr:
            content_length = int(contlenstr)
            if content_length > (1024*1024*32): #32mb payload limit
                self.send_response(500)
                self.end_headers(content_type='application/json')
                self.wfile.write(json.dumps({"detail": {
                "msg": "Payload is too big. Max payload size is 32MB.",
                "type": "bad_input",
                }}).encode())
                return
            body = self.rfile.read(content_length)
        elif self.headers.get('transfer-encoding', '').lower()=="chunked":
            content_length = 0
            chunklimit = 0  # do not process more than 512 chunks, prevents bad actors
            body = b''
            try:
                while True:
                    chunklimit += 1
                    line = self.rfile.readline().strip()
                    if line:
                        chunk_length = max(0,int(line, 16))
                        content_length += chunk_length
                    if not line or chunklimit > 512 or content_length > (1024*1024*32): #32mb payload limit
                        self.send_response(500)
                        self.end_headers(content_type='application/json')
                        self.wfile.write(json.dumps({"detail": {
                        "msg": "Payload is too big. Max payload size is 32MB.",
                        "type": "bad_input",
                        }}).encode())
                        return
                    if chunk_length != 0:
                        chunk = self.rfile.read(chunk_length)
                        body += chunk
                    self.rfile.readline()
                    if chunk_length == 0:
                        break
            except Exception as e:
                self.send_response(500)
                self.end_headers(content_type='application/json')
                self.wfile.write(json.dumps({"detail": {
                "msg": "Failed to parse chunked request.",
                "type": "bad_input",
                }}).encode())
                return

        self.path = self.path.rstrip('/')
        response_body = None
        response_code = 200

        if self.path.endswith('/api/extra/tokencount') or self.path.endswith('/api/extra/tokenize'):
            if not self.secure_endpoint():
                return
            try:
                genparams = json.loads(body)
                countprompt = genparams.get('prompt', "")
                tcaddspecial = genparams.get('special', True)
                countdata = tokenize_ids(countprompt,tcaddspecial)
                response_body = (json.dumps({"value": len(countdata),"ids": countdata}).encode())

            except Exception as e:
                utfprint("Count Tokens - Body Error: " + str(e))
                response_code = 400
                response_body = (json.dumps({"value": -1}).encode())

        elif self.path.endswith('/api/extra/detokenize'):
            if not self.secure_endpoint():
                return
            try:
                genparams = json.loads(body)
                tokids = genparams.get('ids', [])
                detokstr = detokenize_ids(tokids)
                response_body = (json.dumps({"result": detokstr,"success":True}).encode())
            except Exception as e:
                utfprint("Detokenize Error: " + str(e))
                response_code = 400
                response_body = (json.dumps({"result": "","success":False}).encode())

        elif self.path.endswith('/api/extra/abort'):
            if not self.secure_endpoint():
                return
            multiuserkey = ""
            try:
                tempbody = json.loads(body)
                if isinstance(tempbody, dict):
                    multiuserkey = tempbody.get('genkey', "")
            except Exception as e:
                multiuserkey = ""
                pass
            if (multiuserkey=="" and requestsinqueue==0) or (multiuserkey!="" and multiuserkey==currentusergenkey):
                ag = handle.abort_generate()
                time.sleep(0.1) #short delay before replying
                response_body = (json.dumps({"success": ("true" if ag else "false"), "done":"true"}).encode())
                print("\nGeneration Aborted")
            elif (multiuserkey!="" and requestsinqueue>0):
                pendingabortkey = multiuserkey
                response_body = (json.dumps({"success": "true", "done":"false"}).encode())
            else:
                response_body = (json.dumps({"success": "false", "done":"false"}).encode())

        elif self.path.endswith('/api/extra/generate/check'):
            if not self.secure_endpoint():
                return
            pendtxtStr = ""
            multiuserkey = ""
            try:
                tempbody = json.loads(body)
                if isinstance(tempbody, dict):
                    multiuserkey = tempbody.get('genkey', "")
            except Exception as e:
                multiuserkey = ""

            if totalgens>0:
                if (multiuserkey=="" and multiuserkey==currentusergenkey and requestsinqueue==0) or (multiuserkey!="" and multiuserkey==currentusergenkey): #avoid leaking prompts in multiuser
                    pendtxt = handle.get_pending_output()
                    pendtxtStr = ctypes.string_at(pendtxt).decode("UTF-8","ignore")
            response_body = (json.dumps({"results": [{"text": pendtxtStr}]}).encode())

        elif self.path.endswith('/api/extra/last_logprobs'):
            if not self.secure_endpoint():
                return
            logprobsdict = None
            multiuserkey = ""
            try:
                tempbody = json.loads(body)
                if isinstance(tempbody, dict):
                    multiuserkey = tempbody.get('genkey', "")
            except Exception as e:
                multiuserkey = ""

            if totalgens>0:
                if (multiuserkey=="" and multiuserkey==currentusergenkey and requestsinqueue==0) or (multiuserkey!="" and multiuserkey==currentusergenkey): #avoid leaking prompts in multiuser
                    lastlogprobs = handle.last_logprobs()
                    logprobsdict = parse_last_logprobs(lastlogprobs)
            response_body = (json.dumps({"logprobs":logprobsdict}).encode())

        elif self.path.endswith('/api/extra/multiplayer/status'):
            if not self.secure_endpoint():
                return
            if not has_multiplayer:
                response_body = (json.dumps({"error":"Multiplayer not enabled!"}).encode())
            else:
                sender = ""
                senderbusy = False
                try:
                    tempbody = json.loads(body)
                    if isinstance(tempbody, dict):
                        sender = tempbody.get('sender', "")
                        senderbusy = tempbody.get('senderbusy', False)
                except Exception as e:
                    pass
                if sender!="" and senderbusy:
                    multiplayer_lastactive[sender] = int(time.time())
                response_body = (json.dumps({"turn_major":multiplayer_turn_major,"turn_minor":multiplayer_turn_minor,"idle":self.get_multiplayer_idle_state(sender),"data_format":multiplayer_dataformat}).encode())

        elif self.path.endswith('/api/extra/multiplayer/getstory'):
            if not self.secure_endpoint():
                return
            if not has_multiplayer:
                response_body = ("".encode())
            elif multiplayer_story_data_compressed is None:
                response_body = ("".encode())
            else:
                response_body = multiplayer_story_data_compressed.encode()

        elif self.path.endswith('/api/extra/multiplayer/setstory'):
            if not self.secure_endpoint():
                return
            if not has_multiplayer:
                response_code = 400
                response_body = (json.dumps({"success":False, "error":"Multiplayer not enabled!"}).encode())
            else:
                try:
                    incoming_story = json.loads(body) # ensure submitted data is valid json
                    fullupdate = incoming_story.get('full_update', False)
                    dataformat = incoming_story.get('data_format', "")
                    sender = incoming_story.get('sender', "")
                    storybody = incoming_story.get('data', None) #should be a compressed string
                    if storybody:
                        storybody = str(storybody)
                        if len(storybody) > (1024*1024*3): #limit story to 3mb
                            response_code = 400
                            response_body = (json.dumps({"success":False, "error":"Story is too long!"}).encode())
                        else:
                            multiplayer_story_data_compressed = str(storybody) #save latest story
                            multiplayer_dataformat = dataformat
                            if sender!="":
                                multiplayer_lastactive[sender] = int(time.time())
                            if fullupdate:
                                multiplayer_turn_minor = 1
                                multiplayer_turn_major += 1
                            else:
                                multiplayer_turn_minor += 1
                            response_body = (json.dumps({"success":True,"turn_major":multiplayer_turn_major,"turn_minor":multiplayer_turn_minor,"idle":self.get_multiplayer_idle_state(sender),"data_format":multiplayer_dataformat}).encode())
                    else:
                        response_code = 400
                        response_body = (json.dumps({"success":False, "error":"No story submitted!"}).encode())
                except Exception as e:
                    utfprint("Multiplayer Set Story - Body Error: " + str(e))
                    response_code = 400
                    response_body = (json.dumps({"success": False, "error":"Submitted story invalid!"}).encode())

        if response_body is not None:
            self.send_response(response_code)
            self.send_header('content-length', str(len(response_body)))
            self.end_headers(content_type='application/json')
            self.wfile.write(response_body)
            return

        reqblocking = False
        muint = int(args.multiuser)
        if muint<=0 and ((args.whispermodel and args.whispermodel!="") or (args.sdmodel and args.sdmodel!="")):
            muint = 2 # this prevents errors when using voice/img together with text
        multiuserlimit = ((muint-1) if muint > 1 else 6)
        #backwards compatibility for up to 7 concurrent requests, use default limit of 7 if multiuser set to 1
        if muint > 0 and requestsinqueue < multiuserlimit:
            reqblocking = True
            requestsinqueue += 1
        if not modelbusy.acquire(blocking=reqblocking):
            self.send_response(503)
            self.end_headers(content_type='application/json')
            self.wfile.write(json.dumps({"detail": {
                    "msg": "Server is busy; please try again later.",
                    "type": "service_unavailable",
                }}).encode())
            return
        if reqblocking:
            requestsinqueue = (requestsinqueue - 1) if requestsinqueue > 0 else 0

        try:
            sse_stream_flag = False

            api_format = 0 #1=basic,2=kai,3=oai,4=oai-chat,5=interrogate,6=ollama,7=ollamachat
            is_imggen = False
            is_comfyui_imggen = False
            is_transcribe = False

            if self.path.endswith('/request'):
                api_format = 1

            if self.path.endswith(('/api/v1/generate', '/api/latest/generate')):
                api_format = 2

            if self.path.endswith('/api/extra/generate/stream'):
                api_format = 2
                sse_stream_flag = True

            if self.path.endswith('/v1/completions') or self.path.endswith('/v1/completion'):
                api_format = 3

            if self.path.endswith('/v1/chat/completions'):
                api_format = 4

            if self.path.endswith('/sdapi/v1/interrogate'):
                has_vision = (mmprojpath!="")
                if not has_vision:
                    self.send_response(503)
                    self.end_headers(content_type='application/json')
                    self.wfile.write(json.dumps({"detail": {
                            "msg": "No Vision model loaded",
                            "type": "service_unavailable",
                        }}).encode())
                    return
                api_format = 5

            if self.path.endswith('/api/generate'):
                api_format = 6
            if self.path.endswith('/api/chat'):
                api_format = 7

            if self.path=="/prompt" or self.path.endswith('/sdapi/v1/txt2img') or self.path.endswith('/sdapi/v1/img2img'):
                is_imggen = True
                if self.path=="/prompt":
                    is_comfyui_imggen = True

            if self.path.endswith('/api/extra/transcribe') or self.path.endswith('/v1/audio/transcriptions'):
                is_transcribe = True

            if is_imggen or is_transcribe or api_format > 0:
                global last_req_time
                last_req_time = time.time()

                if not is_imggen and not is_transcribe and api_format!=5:
                    if not self.secure_endpoint():
                        return

                genparams = None
                try:
                    genparams = json.loads(body)
                except Exception as e:
                    genparams = None
                    if is_transcribe: #fallback handling of file uploads
                        b64wav = self.extract_b64string_from_file_upload(body)
                        if b64wav:
                            genparams = {"audio_data":b64wav}

                    if not genparams:
                        utfprint("Body Err: " + str(body))
                        self.send_response(500)
                        self.end_headers(content_type='application/json')
                        self.wfile.write(json.dumps({"detail": {
                        "msg": "Error parsing input.",
                        "type": "bad_input",
                        }}).encode())
                        return

                is_quiet = args.quiet
                if (args.debugmode != -1 and not is_quiet) or args.debugmode >= 1:
                    utfprint(f"\nInput: " + json.dumps(genparams))

                if args.foreground:
                    bring_terminal_to_foreground()

                if api_format > 0:#text gen
                    # Check if streaming chat completions, if so, set stream mode to true
                    if (api_format == 4 or api_format == 3) and "stream" in genparams and genparams["stream"]:
                        sse_stream_flag = True

                    gen = asyncio.run(self.handle_request(genparams, api_format, sse_stream_flag))

                    try:
                        # Headers are already sent when streaming
                        if not sse_stream_flag:
                            self.send_response(200)
                            genresp = (json.dumps(gen).encode())
                            self.send_header('content-length', str(len(genresp)))
                            self.end_headers(content_type='application/json')
                            self.wfile.write(genresp)
                    except Exception as ex:
                        if args.debugmode:
                            print(ex)
                        print("Generate: The response could not be sent, maybe connection was terminated?")
                        handle.abort_generate()
                        time.sleep(0.2) #short delay
                    return

                elif is_imggen: #image gen
                    try:
                        if is_comfyui_imggen:
                            lastgeneratedcomfyimg = b''
                            genparams = sd_comfyui_tranform_params(genparams)
                        gen = sd_generate(genparams)
                        genresp = None
                        if is_comfyui_imggen:
                            if gen:
                                lastgeneratedcomfyimg = base64.b64decode(gen)
                            else:
                                lastgeneratedcomfyimg = b''
                            genresp = (json.dumps({"prompt_id": "12345678-0000-0000-0000-000000000001","number": 0,"node_errors":{}}).encode())
                        else:
                            genresp = (json.dumps({"images":[gen],"parameters":{},"info":""}).encode())
                        self.send_response(200)
                        self.send_header('content-length', str(len(genresp)))
                        self.end_headers(content_type='application/json')
                        self.wfile.write(genresp)
                    except Exception as ex:
                        if args.debugmode:
                            print(ex)
                        print("Generate Image: The response could not be sent, maybe connection was terminated?")
                        time.sleep(0.2) #short delay
                    return
                elif is_transcribe:
                    try:
                        gen = whisper_generate(genparams)
                        genresp = (json.dumps({"text":gen}).encode())
                        self.send_response(200)
                        self.send_header('content-length', str(len(genresp)))
                        self.end_headers(content_type='application/json')
                        self.wfile.write(genresp)
                    except Exception as ex:
                        if args.debugmode:
                            print(ex)
                        print("Transcribe: The response could not be sent, maybe connection was terminated?")
                        time.sleep(0.2) #short delay
                    return

        finally:
            time.sleep(0.05)
            modelbusy.release()

        self.send_response(404)
        self.end_headers(content_type='text/html')


    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers(content_type='text/html')

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers(content_type='text/html')

    def end_headers(self, content_type=None):
        self.send_header('access-control-allow-origin', '*')
        self.send_header('access-control-allow-methods', '*')
        self.send_header('access-control-allow-headers', '*, Accept, Content-Type, Content-Length, Cache-Control, Accept-Encoding, X-CSRF-Token, Client-Agent, X-Fields, Content-Type, Authorization, X-Requested-With, X-HTTP-Method-Override, apikey, genkey')
        self.send_header("cache-control", "no-store")
        if content_type is not None:
            self.send_header('content-type', content_type)
        return super(ServerRequestHandler, self).end_headers()

def is_port_in_use(portNum):
    try:
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(('localhost', portNum)) == 0
    except Exception as ex:
        return True

def is_ipv6_supported():
    try:
        # Attempt to create an IPv6 socket
        sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        sock.close()
        return True
    except Exception as ex:
        return False

def RunServerMultiThreaded(addr, port):
    global exitcounter, sslvalid
    global embedded_kailite, embedded_kcpp_docs, embedded_kcpp_sdui
    if is_port_in_use(port):
        print(f"Warning: Port {port} already appears to be in use by another program.")
    ipv4_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    ipv4_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    ipv6_sock = None
    if is_ipv6_supported():
        ipv6_sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        ipv6_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        ipv6_sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)

    if args.ssl and sslvalid:
        import ssl
        certpath = os.path.abspath(args.ssl[0])
        keypath = os.path.abspath(args.ssl[1])
        context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        context.load_cert_chain(certfile=certpath, keyfile=keypath)
        ipv4_sock = context.wrap_socket(ipv4_sock, server_side=True)
        if ipv6_sock:
            ipv6_sock = context.wrap_socket(ipv6_sock, server_side=True)

    numThreads = 24
    ipv4_sock.bind((addr, port))
    ipv4_sock.listen(numThreads)

    if ipv6_sock:
        try:
            ipv6_sock.bind((addr, port))
            ipv6_sock.listen(numThreads)
        except Exception as ex:
            ipv6_sock = None
            print("IPv6 Socket Failed to Bind. IPv6 will be unavailable.")

    class Thread(threading.Thread):
        def __init__(self, i):
            threading.Thread.__init__(self)
            self.i = i
            self.daemon = True
            self.start()

        def run(self):
            global exitcounter
            handler = ServerRequestHandler(addr, port)
            with http.server.HTTPServer((addr, port), handler, False) as self.httpd:
                try:
                    if ipv6_sock:
                        self.httpd.socket = ipv4_sock if self.i < 16 else ipv6_sock
                    else:
                        self.httpd.socket = ipv4_sock

                    self.httpd.server_bind = self.server_close = lambda self: None
                    self.httpd.serve_forever()
                except (KeyboardInterrupt,SystemExit):
                    exitcounter = 999
                    self.httpd.server_close()
                    sys.exit(0)
                finally:
                    exitcounter = 999
                    self.httpd.server_close()
                    os._exit(0)
        def stop(self):
            global exitcounter
            exitcounter = 999
            self.httpd.server_close()

    threadArr = []
    for i in range(numThreads):
        threadArr.append(Thread(i))
    while 1:
        try:
            time.sleep(10)
        except KeyboardInterrupt:
            global exitcounter
            exitcounter = 999
            for i in range(numThreads):
                threadArr[i].stop()
            sys.exit(0)

# note: customtkinter-5.2.0
def show_gui():
    global guimode
    guimode = True
    from tkinter.filedialog import askopenfilename
    from tkinter.filedialog import asksaveasfile

    # if args received, launch
    if len(sys.argv) != 1 and not args.showgui:
        import tkinter as tk
        root = tk.Tk() #we dont want the useless window to be visible, but we want it in taskbar
        root.attributes("-alpha", 0)
        args.model_param = askopenfilename(title="Select ggml model .bin or .gguf file or .kcpps config")
        root.withdraw()
        root.quit()
        if args.model_param and args.model_param!="" and (args.model_param.lower().endswith('.kcpps') or args.model_param.lower().endswith('.kcppt')):
            load_config_cli(args.model_param)
        if not args.model_param and not args.sdmodel and not args.whispermodel and not args.nomodel:
            global exitcounter
            exitcounter = 999
            exit_with_error(2,"No ggml model or kcpps file was selected. Exiting.")
        return

    #dummy line to get darkdetect imported in pyinstaller
    try:
        import darkdetect as darkdt
        darkdt.isDark()
        pass
    except Exception as e:
        pass

    import customtkinter as ctk
    nextstate = 0 #0=exit, 1=launch
    original_windowwidth = 580
    original_windowheight = 560
    windowwidth = original_windowwidth
    windowheight = original_windowheight
    ctk.set_appearance_mode("dark")
    root = ctk.CTk()
    root.geometry(str(windowwidth) + "x" + str(windowheight))
    root.title(f"KoboldCpp v{KcppVersion}")

    gtooltip_box = None
    gtooltip_label = None

    window_reference_width = None
    window_reference_height = None
    previous_event_width = None
    previous_event_height = None
    def on_resize(event):
        if not event.widget.master:
            nonlocal window_reference_width, window_reference_height, previous_event_width,previous_event_height
            if not window_reference_width and not window_reference_height:
                window_reference_width = event.width
                window_reference_height = event.height
                previous_event_width = window_reference_width
                previous_event_height = window_reference_height
            else:
                new_width = event.width
                new_height = event.height
                incr_w = new_width/window_reference_width
                incr_h = new_height/window_reference_height
                smallratio = min(incr_w,incr_h)
                smallratio = round(smallratio,2)
                if new_width != previous_event_width or new_height!=previous_event_height:
                    lastpos = root.geometry()
                    lparr = lastpos.split('+', 1)
                    lastpos = ("+"+str(lparr[1])) if (len(lparr)==2) else ""
                    previous_event_width = new_width
                    previous_event_height = new_height
                    windowwidth = math.floor(original_windowwidth*smallratio)
                    windowwidth = max(256, min(1024, windowwidth))
                    windowheight = math.floor(original_windowheight*smallratio)
                    windowheight = max(256, min(1024, windowheight))
                    root.geometry(str(windowwidth) + "x" + str(windowheight) + str(lastpos))
                    ctk.set_widget_scaling(smallratio)
                    changerunmode(1,1,1)
                    togglerope(1,1,1)
                    toggleflashattn(1,1,1)
                    togglectxshift(1,1,1)
                    togglehorde(1,1,1)
                    togglesdquant(1,1,1)
                    toggletaesd(1,1,1)

    if sys.platform=="darwin":
        root.resizable(False,False)
    else:
        root.resizable(True,True)
        root.bind("<Configure>", on_resize)
    global using_gui_launcher
    using_gui_launcher = True
    kcpp_exporting_template = False

    # trigger empty tooltip then remove it
    def show_tooltip(event, tooltip_text=None):
        nonlocal gtooltip_box, gtooltip_label
        if not gtooltip_box and not gtooltip_label:
            gtooltip_box = ctk.CTkToplevel(root)
            gtooltip_box.configure(fg_color="#ffffe0")
            gtooltip_box.withdraw()
            gtooltip_box.overrideredirect(True)
            gtooltip_label = ctk.CTkLabel(gtooltip_box, text=tooltip_text, text_color="#000000", fg_color="#ffffe0")
            gtooltip_label.pack(expand=True, ipadx=2, ipady=1)
        else:
            gtooltip_label.configure(text=tooltip_text)

        x, y = root.winfo_pointerxy()
        gtooltip_box.wm_geometry(f"+{x + 10}+{y + 10}")
        gtooltip_box.deiconify()

    def hide_tooltip(event):
        nonlocal gtooltip_box
        if gtooltip_box:
            gtooltip_box.withdraw()
    show_tooltip(None,"") #initialize tooltip objects
    hide_tooltip(None)

    default_threads = get_default_threads()

    tabs = ctk.CTkFrame(root, corner_radius = 0, width=windowwidth, height=windowheight-50)
    tabs.grid(row=0, stick="nsew")
    tabnames= ["Quick Launch", "Hardware", "Tokens", "Model Files", "Network", "Horde Worker","Image Gen","Audio","Extra"]
    navbuttons = {}
    navbuttonframe = ctk.CTkFrame(tabs, width=100, height=int(tabs.cget("height")))
    navbuttonframe.grid(row=0, column=0, padx=2,pady=2)
    navbuttonframe.grid_propagate(False)

    tabcontentframe = ctk.CTkFrame(tabs, width=windowwidth - int(navbuttonframe.cget("width")), height=int(tabs.cget("height")))
    tabcontentframe.grid(row=0, column=1, sticky="nsew", padx=2, pady=2)
    tabcontentframe.grid_propagate(False)

    tabcontent = {}
    # slider data
    blasbatchsize_values = ["-1", "32", "64", "128", "256", "512", "1024", "2048"]
    blasbatchsize_text = ["Don't Batch BLAS","32","64","128","256","512","1024","2048"]
    contextsize_text = ["256", "512", "1024", "2048", "3072", "4096", "6144", "8192", "12288", "16384", "24576", "32768", "49152", "65536", "98304", "131072"]
    antirunopts = [opt.replace("Use ", "") for lib, opt in lib_option_pairs if not (opt in runopts)]
    quantkv_text = ["F16 (Off)","8-Bit","4-Bit"]

    if not any(runopts):
        exitcounter = 999
        exit_with_error(2,"KoboldCPP couldn't locate any backends to use (i.e Default, Vulkan, CLBlast, CuBLAS).\n\nTo use the program, please run the 'make' command from the directory.","No Backends Available!")

    # Vars - should be in scope to be used by multiple widgets
    gpulayers_var = ctk.StringVar(value="-1")
    threads_var = ctk.StringVar(value=str(default_threads))
    runopts_var = ctk.StringVar()
    gpu_choice_var = ctk.StringVar(value="1")

    launchbrowser = ctk.IntVar(value=1)
    highpriority = ctk.IntVar()
    disablemmap = ctk.IntVar()
    usemlock = ctk.IntVar()
    debugmode = ctk.IntVar()
    keepforeground = ctk.IntVar()
    quietmode = ctk.IntVar(value=0)
    nocertifymode = ctk.IntVar(value=0)

    lowvram_var = ctk.IntVar()
    mmq_var = ctk.IntVar(value=1)
    quantkv_var = ctk.IntVar(value=0)
    blas_threads_var = ctk.StringVar()
    blas_size_var = ctk.IntVar()
    version_var = ctk.StringVar(value="0")
    tensor_split_str_vars = ctk.StringVar(value="")
    rowsplit_var = ctk.IntVar()

    contextshift = ctk.IntVar(value=1)
    fastforward = ctk.IntVar(value=1)
    remotetunnel = ctk.IntVar(value=0)
    smartcontext = ctk.IntVar()
    flashattention = ctk.IntVar(value=0)
    context_var = ctk.IntVar()
    customrope_var = ctk.IntVar()
    customrope_scale = ctk.StringVar(value="1.0")
    customrope_base = ctk.StringVar(value="10000")
    chatcompletionsadapter_var = ctk.StringVar()

    model_var = ctk.StringVar()
    lora_var = ctk.StringVar()
    lora_base_var = ctk.StringVar()
    preloadstory_var = ctk.StringVar()
    mmproj_var = ctk.StringVar()
    draftmodel_var = ctk.StringVar()
    draftamount_var = ctk.StringVar(value=str(default_draft_amount))
    nomodel = ctk.IntVar(value=0)

    port_var = ctk.StringVar(value=defaultport)
    host_var = ctk.StringVar(value="")
    multiuser_var = ctk.IntVar(value=1)
    multiplayer_var = ctk.IntVar(value=has_multiplayer)
    horde_name_var = ctk.StringVar(value="koboldcpp")
    horde_gen_var = ctk.StringVar(value=maxhordelen)
    horde_context_var = ctk.StringVar(value=maxhordectx)
    horde_apikey_var = ctk.StringVar(value="")
    horde_workername_var = ctk.StringVar(value="")
    usehorde_var = ctk.IntVar()
    ssl_cert_var = ctk.StringVar()
    ssl_key_var = ctk.StringVar()
    password_var = ctk.StringVar()

    sd_model_var = ctk.StringVar()
    sd_lora_var = ctk.StringVar()
    sd_loramult_var = ctk.StringVar(value="1.0")
    sd_vae_var = ctk.StringVar()
    sd_t5xxl_var = ctk.StringVar()
    sd_clipl_var = ctk.StringVar()
    sd_clipg_var = ctk.StringVar()
    sd_vaeauto_var = ctk.IntVar(value=0)
    sd_clamped_var = ctk.StringVar(value="0")
    sd_threads_var = ctk.StringVar(value=str(default_threads))
    sd_quant_var = ctk.IntVar(value=0)

    whisper_model_var = ctk.StringVar()

    def tabbuttonaction(name):
        for t in tabcontent:
            if name == t:
                tabcontent[t].grid(row=0, column=0)
                navbuttons[t].configure(fg_color="#6f727b")
            else:
                tabcontent[t].grid_remove()
                navbuttons[t].configure(fg_color="transparent")

    # Dynamically create tabs + buttons based on values of [tabnames]
    for idx, name in enumerate(tabnames):
        tabcontent[name] = ctk.CTkFrame(tabcontentframe, width=int(tabcontentframe.cget("width")), height=int(tabcontentframe.cget("height")), fg_color="transparent")
        tabcontent[name].grid_propagate(False)
        if idx == 0:
            tabcontent[name].grid(row=idx, sticky="nsew")
        ctk.CTkLabel(tabcontent[name], text= name, font=ctk.CTkFont(None, 14, 'bold')).grid(row=0, padx=12, pady = 5, stick='nw')

        navbuttons[name] = ctk.CTkButton(navbuttonframe, text=name, width = 100, corner_radius=0 , command = lambda d=name:tabbuttonaction(d), hover_color="#868a94" )
        navbuttons[name].grid(row=idx)

    tabbuttonaction(tabnames[0])
    # Quick Launch Tab
    quick_tab = tabcontent["Quick Launch"]

    # helper functions
    def makecheckbox(parent, text, variable=None, row=0, column=0, command=None, onvalue=1, offvalue=0,tooltiptxt=""):
        temp = ctk.CTkCheckBox(parent, text=text,variable=variable, onvalue=onvalue, offvalue=offvalue)
        if command is not None and variable is not None:
            variable.trace("w", command)
        temp.grid(row=row,column=column, padx=8, pady=1, stick="nw")
        if tooltiptxt!="":
            temp.bind("<Enter>", lambda event: show_tooltip(event, tooltiptxt))
            temp.bind("<Leave>", hide_tooltip)
        return temp

    def makelabel(parent, text, row, column=0, tooltiptxt="", columnspan=1, padx=8):
        temp = ctk.CTkLabel(parent, text=text)
        temp.grid(row=row, column=column, padx=padx, pady=1, stick="nw", columnspan=columnspan)
        if tooltiptxt!="":
            temp.bind("<Enter>", lambda event: show_tooltip(event, tooltiptxt))
            temp.bind("<Leave>", hide_tooltip)
        return temp

    def makeslider(parent, label, options, var, from_ , to,  row=0, width=160, height=10, set=0, tooltip=""):
        sliderLabel = makelabel(parent, options[set], row + 1, 0, columnspan=2, padx=(width+12))
        titleLabel = makelabel(parent, label, row,0,tooltip)

        def sliderUpdate(a,b,c):
            sliderLabel.configure(text = options[int(var.get())])
        var.trace("w", sliderUpdate)
        slider = ctk.CTkSlider(parent, from_=from_, to=to, variable = var, width = width, height=height, border_width=5,number_of_steps=len(options) - 1)
        slider.grid(row=row+1,  column=0, padx = 8, stick="w", columnspan=2)
        slider.set(set)
        return slider, sliderLabel, titleLabel


    def makelabelentry(parent, text, var, row=0, width=50, padx=8, singleline=False, tooltip=""):
        label = makelabel(parent, text, row, 0, tooltip)
        entry = ctk.CTkEntry(parent, width=width, textvariable=var)
        entry.grid(row=row, column=(0 if singleline else 1), padx=padx, sticky="nw")
        return entry, label

    def makefileentry(parent, text, searchtext, var, row=0, width=200, filetypes=[], onchoosefile=None, singlerow=False, singlecol=True, tooltiptxt=""):
        label = makelabel(parent, text, row,0,tooltiptxt,columnspan=3)
        def getfilename(var, text):
            initialDir = os.path.dirname(var.get())
            initialDir = initialDir if os.path.isdir(initialDir) else None
            fnam = askopenfilename(title=text,filetypes=filetypes, initialdir=initialDir)
            if fnam:
                var.set(fnam)
                if onchoosefile:
                    onchoosefile(var.get())
        entry = ctk.CTkEntry(parent, width, textvariable=var)
        button = ctk.CTkButton(parent, 50, text="Browse", command= lambda a=var,b=searchtext:getfilename(a,b))
        if singlerow:
            if singlecol:
                entry.grid(row=row, column=0, padx=(94+8), stick="w")
                button.grid(row=row, column=0, padx=(94+width+12), stick="nw")
            else:
                entry.grid(row=row, column=1, padx=8, stick="w")
                button.grid(row=row, column=1, padx=(width+12), stick="nw")
        else:
            if singlecol:
                entry.grid(row=row+1, column=0, columnspan=3, padx=8, stick="nw")
                button.grid(row=row+1, column=0, columnspan=3, padx=(width+12), stick="nw")
            else:
                entry.grid(row=row+1, column=0, columnspan=1, padx=8, stick="nw")
                button.grid(row=row+1, column=1, columnspan=1, padx=8, stick="nw")
        return label, entry, button

    # decided to follow yellowrose's and kalomaze's suggestions, this function will automatically try to determine GPU identifiers
    # run in new thread so it doesnt block. does not return anything, instead overwrites specific values and redraws GUI
    def auto_set_backend_gui(manual_select=False):
        global exitcounter, runmode_untouched
        if manual_select:
            print("\nA .kcppt template was selected from GUI - automatically selecting your backend...")
            runmode_untouched = True
            fetch_gpu_properties(False,True,True)
        else:
            fetch_gpu_properties(True,True,True)
        found_new_backend = False
        #autopick cublas if suitable, requires at least 3.5GB VRAM to auto pick
        #we do not want to autoselect hip/cublas if the user has already changed their desired backend!
        if exitcounter < 100 and MaxMemory[0]>3500000000 and (("Use CuBLAS" in runopts and CUDevicesNames[0]!="") or "Use hipBLAS (ROCm)" in runopts) and (any(CUDevicesNames) or any(CLDevicesNames)) and runmode_untouched:
            if "Use CuBLAS" in runopts:
                runopts_var.set("Use CuBLAS")
                gpu_choice_var.set("1")
                print("Auto Selected CUDA Backend...\n")
                found_new_backend = True
            elif "Use hipBLAS (ROCm)" in runopts:
                runopts_var.set("Use hipBLAS (ROCm)")
                gpu_choice_var.set("1")
                print("Auto Selected HIP Backend...\n")
                found_new_backend = True
        elif exitcounter < 100 and (1 in VKIsDGPU) and runmode_untouched and "Use Vulkan" in runopts:
            for i in range(0,len(VKIsDGPU)):
                if VKIsDGPU[i]==1:
                    runopts_var.set("Use Vulkan")
                    gpu_choice_var.set(str(i+1))
                    print("Auto Selected Vulkan Backend...\n")
                    found_new_backend = True
                    break
        if not found_new_backend:
            print("Auto Selected Default Backend...\n")
        changed_gpu_choice_var()

    def on_picked_model_file(filepath):
        if filepath.lower().endswith('.kcpps') or filepath.lower().endswith('.kcppt'):
            #load it as a config file instead
            with open(filepath, 'r') as f:
                dict = json.load(f)
                import_vars(dict)

    def setup_backend_tooltip(parent):
        # backend count label with the tooltip function
        nl = '\n'
        tooltxt = f"Number of backends you have built and available." + (f"\n\nMissing Backends: \n\n{nl.join(antirunopts)}" if len(runopts) < 8 else "")
        num_backends_built = makelabel(parent, str(len(runopts)) + f"/8", 5, 2,tooltxt)
        num_backends_built.grid(row=1, column=1, padx=195, pady=0)
        num_backends_built.configure(text_color="#00ff00")

    def gui_changed_modelfile(*args):
        global importvars_in_progress
        if not importvars_in_progress:
            filepath = model_var.get()
            sdfilepath = sd_model_var.get()
            whisperfilepath = whisper_model_var.get()
            mmprojfilepath = mmproj_var.get()
            draftmodelpath = draftmodel_var.get()
            extract_modelfile_params(filepath,sdfilepath,whisperfilepath,mmprojfilepath,draftmodelpath)
            changed_gpulayers_estimate()
        pass

    def changed_gpulayers_estimate(*args):
        predicted_gpu_layers = autoset_gpu_layers(int(contextsize_text[context_var.get()]),(sd_quant_var.get()==1),int(blasbatchsize_values[int(blas_size_var.get())]))
        max_gpu_layers = (f"/{modelfile_extracted_meta[0][0]+3}" if (modelfile_extracted_meta and modelfile_extracted_meta[0] and modelfile_extracted_meta[0][0]!=0) else "")
        index = runopts_var.get()
        gpu_be = (index == "Use Vulkan" or index == "Use Vulkan (Old CPU)" or index == "Use CLBlast" or index == "Use CLBlast (Old CPU)" or index == "Use CuBLAS" or index == "Use hipBLAS (ROCm)")
        layercounter_label.grid(row=6, column=1, padx=75, sticky="W")
        quick_layercounter_label.grid(row=6, column=1, padx=75, sticky="W")
        if sys.platform=="darwin" and gpulayers_var.get()=="-1":
            quick_layercounter_label.configure(text=f"(Auto: All Layers)")
            layercounter_label.configure(text=f"(Auto: All Layers)")
        elif gpu_be and gpulayers_var.get()=="-1" and predicted_gpu_layers>0:
            quick_layercounter_label.configure(text=f"(Auto: {predicted_gpu_layers}{max_gpu_layers} Layers)")
            layercounter_label.configure(text=f"(Auto: {predicted_gpu_layers}{max_gpu_layers} Layers)")
        elif gpu_be and gpulayers_var.get()=="-1" and predicted_gpu_layers<=0 and (modelfile_extracted_meta and modelfile_extracted_meta[1]):
            quick_layercounter_label.configure(text=f"(Auto: No Offload)")
            layercounter_label.configure(text=f"(Auto: No Offload)")
        elif gpu_be and gpulayers_var.get()=="":
            quick_layercounter_label.configure(text=f"(Set -1 for Auto)")
            layercounter_label.configure(text=f"(Set -1 for Auto)")
        else:
            layercounter_label.grid_remove()
            quick_layercounter_label.grid_remove()
        pass

    def changed_gpu_choice_var(*args):
        global exitcounter
        if exitcounter > 100:
            return
        if gpu_choice_var.get()!="All":
            try:
                s = int(gpu_choice_var.get())-1
                v = runopts_var.get()
                if v == "Use Vulkan" or v == "Use Vulkan (Old CPU)":
                    quick_gpuname_label.configure(text=VKDevicesNames[s])
                    gpuname_label.configure(text=VKDevicesNames[s])
                elif v == "Use CLBlast" or v == "Use CLBlast (Old CPU)":
                    quick_gpuname_label.configure(text=CLDevicesNames[s])
                    gpuname_label.configure(text=CLDevicesNames[s])
                else:
                    quick_gpuname_label.configure(text=CUDevicesNames[s])
                    gpuname_label.configure(text=CUDevicesNames[s])
            except Exception as ex:
                pass
        else:
            quick_gpuname_label.configure(text="")
            gpuname_label.configure(text="")

    gpu_choice_var.trace("w", changed_gpu_choice_var)
    gpulayers_var.trace("w", changed_gpulayers_estimate)

    def togglefastforward(a,b,c):
        if fastforward.get()==0:
            contextshift.set(0)
            smartcontext.set(0)
            togglectxshift(1,1,1)

    def togglectxshift(a,b,c):
        if contextshift.get()==0:
            smartcontextbox.grid()
        else:
            fastforward.set(1)
            smartcontextbox.grid_remove()

        if contextshift.get()==0 and flashattention.get()==1:
            qkvslider.grid()
            qkvlabel.grid()
            noqkvlabel.grid_remove()
        else:
            qkvslider.grid_remove()
            qkvlabel.grid_remove()
            noqkvlabel.grid()

    def toggleflashattn(a,b,c):
        if contextshift.get()==0 and flashattention.get()==1:
            qkvslider.grid()
            qkvlabel.grid()
            noqkvlabel.grid_remove()
        else:
            qkvslider.grid_remove()
            qkvlabel.grid_remove()
            noqkvlabel.grid()


    def guibench():
        args.benchmark = "stdout"
        launchbrowser.set(0)
        guilaunch()

    def changerunmode(a,b,c):
        global runmode_untouched
        runmode_untouched = False
        index = runopts_var.get()
        if index == "Use Vulkan" or index == "Use Vulkan (Old CPU)" or index == "Use CLBlast" or index == "Use CLBlast (Old CPU)" or index == "Use CuBLAS" or index == "Use hipBLAS (ROCm)":
            quick_gpuname_label.grid(row=3, column=1, padx=75, sticky="W")
            gpuname_label.grid(row=3, column=1, padx=75, sticky="W")
            gpu_selector_label.grid(row=3, column=0, padx = 8, pady=1, stick="nw")
            quick_gpu_selector_label.grid(row=3, column=0, padx = 8, pady=1, stick="nw")
            if index == "Use CLBlast" or index == "Use CLBlast (Old CPU)":
                gpu_selector_box.grid(row=3, column=1, padx=8, pady=1, stick="nw")
                quick_gpu_selector_box.grid(row=3, column=1, padx=8, pady=1, stick="nw")
                CUDA_gpu_selector_box.grid_remove()
                CUDA_quick_gpu_selector_box.grid_remove()
                if gpu_choice_var.get()=="All":
                    gpu_choice_var.set("1")
            elif index == "Use Vulkan" or index == "Use Vulkan (Old CPU)" or index == "Use CuBLAS" or index == "Use hipBLAS (ROCm)":
                gpu_selector_box.grid_remove()
                quick_gpu_selector_box.grid_remove()
                CUDA_gpu_selector_box.grid(row=3, column=1, padx=8, pady=1, stick="nw")
                CUDA_quick_gpu_selector_box.grid(row=3, column=1, padx=8, pady=1, stick="nw")
        else:
            quick_gpuname_label.grid_remove()
            gpuname_label.grid_remove()
            gpu_selector_label.grid_remove()
            gpu_selector_box.grid_remove()
            CUDA_gpu_selector_box.grid_remove()
            quick_gpu_selector_label.grid_remove()
            quick_gpu_selector_box.grid_remove()
            CUDA_quick_gpu_selector_box.grid_remove()

        if index == "Use CuBLAS" or index == "Use hipBLAS (ROCm)":
            lowvram_box.grid(row=4, column=0, padx=8, pady=1,  stick="nw")
            mmq_box.grid(row=4, column=1, padx=8, pady=1,  stick="nw")
            quick_mmq_box.grid(row=4, column=1, padx=8, pady=1,  stick="nw")
            splitmode_box.grid(row=5, column=1, padx=8, pady=1,  stick="nw")
            tensor_split_label.grid(row=8, column=0, padx = 8, pady=1, stick="nw")
            tensor_split_entry.grid(row=8, column=1, padx=8, pady=1, stick="nw")
        else:
            lowvram_box.grid_remove()
            mmq_box.grid_remove()
            quick_mmq_box.grid_remove()
            tensor_split_label.grid_remove()
            tensor_split_entry.grid_remove()
            splitmode_box.grid_remove()

        if index == "Use Vulkan" or index == "Use Vulkan (Old CPU)":
            tensor_split_label.grid(row=8, column=0, padx = 8, pady=1, stick="nw")
            tensor_split_entry.grid(row=8, column=1, padx=8, pady=1, stick="nw")
            quick_use_flashattn.grid_remove()
        else:
            quick_use_flashattn.grid(row=22, column=1, padx=8, pady=1,  stick="nw")

        if index == "Use Vulkan" or index == "Use Vulkan (Old CPU)" or index == "Use CLBlast" or index == "Use CLBlast (Old CPU)" or index == "Use CuBLAS" or index == "Use hipBLAS (ROCm)":
            gpu_layers_label.grid(row=6, column=0, padx = 8, pady=1, stick="nw")
            gpu_layers_entry.grid(row=6, column=1, padx=8, pady=1, stick="nw")
            quick_gpu_layers_label.grid(row=6, column=0, padx = 8, pady=1, stick="nw")
            quick_gpu_layers_entry.grid(row=6, column=1, padx=8, pady=1, stick="nw")
        elif sys.platform=="darwin":
            gpu_layers_label.grid(row=6, column=0, padx = 8, pady=1, stick="nw")
            gpu_layers_entry.grid(row=6, column=1, padx=8, pady=1, stick="nw")
            quick_gpu_layers_label.grid(row=6, column=0, padx = 8, pady=1, stick="nw")
            quick_gpu_layers_entry.grid(row=6, column=1, padx=8, pady=1, stick="nw")
        else:
            gpu_layers_label.grid_remove()
            gpu_layers_entry.grid_remove()
            quick_gpu_layers_label.grid_remove()
            quick_gpu_layers_entry.grid_remove()
        changed_gpulayers_estimate()
        changed_gpu_choice_var()


    # presets selector
    makelabel(quick_tab, "Presets:", 1,0,"Select a backend to use.\nCuBLAS runs on Nvidia GPUs, and is much faster.\nVulkan and CLBlast works on all GPUs but is somewhat slower.\nOtherwise, runs on CPU only.\nNoAVX2 and Failsafe modes support older PCs.")

    runoptbox = ctk.CTkComboBox(quick_tab, values=runopts, width=180,variable=runopts_var, state="readonly")
    runoptbox.grid(row=1, column=1,padx=8, stick="nw")
    runoptbox.set(runopts[0]) # Set to first available option

    # Tell user how many backends are available
    setup_backend_tooltip(quick_tab)

    # gpu options
    quick_gpu_selector_label = makelabel(quick_tab, "GPU ID:", 3,0,"Which GPU ID to load the model with.\nNormally your main GPU is #1, but it can vary for multi GPU setups.")
    quick_gpu_selector_box = ctk.CTkComboBox(quick_tab, values=CLDevices, width=60, variable=gpu_choice_var, state="readonly")
    CUDA_quick_gpu_selector_box = ctk.CTkComboBox(quick_tab, values=CUDevices, width=60, variable=gpu_choice_var, state="readonly")
    quick_gpuname_label = ctk.CTkLabel(quick_tab, text="")
    quick_gpuname_label.grid(row=3, column=1, padx=75, sticky="W")
    quick_gpuname_label.configure(text_color="#ffff00")
    quick_gpu_layers_entry,quick_gpu_layers_label = makelabelentry(quick_tab,"GPU Layers:", gpulayers_var, 6, 50,tooltip="How many layers to offload onto the GPU.\nVRAM intensive, usage increases with model and context size.\nRequires some trial and error to find the best fit value.\n\nCommon values for total layers, accuracy not guaranteed.\n\nLlama/Mistral 7b/8b: 33\nSolar 10.7b/11b: 49\nLlama 13b: 41\nLlama 20b(stack): 63\nLlama/Yi 34b: 61\nMixtral 8x7b: 33\nLlama 70b: 81")
    quick_layercounter_label = ctk.CTkLabel(quick_tab, text="")
    quick_layercounter_label.grid(row=6, column=1, padx=75, sticky="W")
    quick_layercounter_label.configure(text_color="#ffff00")
    quick_mmq_box = makecheckbox(quick_tab,  "Use QuantMatMul (mmq)", mmq_var, 4,1,tooltiptxt="Enable MMQ mode instead of CuBLAS for prompt processing. Read the wiki. Speed may vary.")

    # quick boxes
    quick_boxes = {
        "Launch Browser": [launchbrowser, "Launches your default browser after model loading is complete"],
        "Disable MMAP": [disablemmap,  "Avoids using mmap to load models if enabled"],
        "Use ContextShift": [contextshift, "Uses Context Shifting to reduce reprocessing.\nRecommended. Check the wiki for more info."],
        "Remote Tunnel": [remotetunnel,  "Creates a trycloudflare tunnel.\nAllows you to access koboldcpp from other devices over an internet URL."],
        "Quiet Mode": [quietmode, "Prevents all generation related terminal output from being displayed."]
    }

    for idx, (name, properties) in enumerate(quick_boxes.items()):
        makecheckbox(quick_tab, name, properties[0], int(idx/2) + 20, idx % 2, tooltiptxt=properties[1])

    quick_use_flashattn = makecheckbox(quick_tab, "Use FlashAttention", flashattention, 22, 1, tooltiptxt="Enable flash attention for GGUF models.")

    # context size
    makeslider(quick_tab, "Context Size:", contextsize_text, context_var, 0, len(contextsize_text)-1, 30, width=280, set=5,tooltip="What is the maximum context size to support. Model specific. You cannot exceed it.\nLarger contexts require more memory, and not all models support it.")

    # load model
    makefileentry(quick_tab, "GGUF Text Model:", "Select GGUF or GGML Model File", model_var, 40, 280, onchoosefile=on_picked_model_file,tooltiptxt="Select a GGUF or GGML model file on disk to be loaded.")
    model_var.trace("w", gui_changed_modelfile)

    # Hardware Tab
    hardware_tab = tabcontent["Hardware"]

    # presets selector
    makelabel(hardware_tab, "Presets:", 1,0,"Select a backend to use.\nCuBLAS runs on Nvidia GPUs, and is much faster.\nVulkan and CLBlast works on all GPUs but is somewhat slower.\nOtherwise, runs on CPU only.\nNoAVX2 and Failsafe modes support older PCs.")
    runoptbox = ctk.CTkComboBox(hardware_tab, values=runopts,  width=180,variable=runopts_var, state="readonly")
    runoptbox.grid(row=1, column=1,padx=8, stick="nw")
    runoptbox.set(runopts[0]) # Set to first available option

    # Tell user how many backends are available
    setup_backend_tooltip(hardware_tab)

    # gpu options
    gpu_selector_label = makelabel(hardware_tab, "GPU ID:", 3,0,"Which GPU ID to load the model with.\nNormally your main GPU is #1, but it can vary for multi GPU setups.")
    gpu_selector_box = ctk.CTkComboBox(hardware_tab, values=CLDevices, width=60, variable=gpu_choice_var, state="readonly")
    CUDA_gpu_selector_box = ctk.CTkComboBox(hardware_tab, values=CUDevices, width=60, variable=gpu_choice_var, state="readonly")
    gpuname_label = ctk.CTkLabel(hardware_tab, text="")
    gpuname_label.grid(row=3, column=1, padx=75, sticky="W")
    gpuname_label.configure(text_color="#ffff00")
    gpu_layers_entry,gpu_layers_label = makelabelentry(hardware_tab,"GPU Layers:", gpulayers_var, 6, 50,tooltip="How many layers to offload onto the GPU.\nVRAM intensive, usage increases with model and context size.\nRequires some trial and error to find the best fit value.\n\nCommon values for total layers, accuracy not guaranteed.\n\nLlama/Mistral 7b/8b: 33\nSolar 10.7b/11b: 49\nLlama 13b: 41\nLlama 20b(stack): 63\nLlama/Yi 34b: 61\nMixtral 8x7b: 33\nLlama 70b: 81")
    layercounter_label = ctk.CTkLabel(hardware_tab, text="")
    layercounter_label.grid(row=6, column=1, padx=75, sticky="W")
    layercounter_label.configure(text_color="#ffff00")
    tensor_split_entry,tensor_split_label = makelabelentry(hardware_tab, "Tensor Split:", tensor_split_str_vars, 8, 80, tooltip='When using multiple GPUs this option controls how large tensors should be split across all GPUs.\nUses a comma-separated list of non-negative values that assigns the proportion of data that each GPU should get in order.\nFor example, "3,2" will assign 60% of the data to GPU 0 and 40% to GPU 1.')
    lowvram_box = makecheckbox(hardware_tab,  "Low VRAM (No KV offload)", lowvram_var, 4,0, tooltiptxt='Avoid offloading KV Cache or scratch buffers to VRAM.\nAllows more layers to fit, but may result in a speed loss.')
    mmq_box = makecheckbox(hardware_tab,  "Use QuantMatMul (mmq)", mmq_var, 4,1, tooltiptxt="Enable MMQ mode to use finetuned kernels instead of default CuBLAS/HipBLAS for prompt processing.\nRead the wiki. Speed may vary.")
    splitmode_box = makecheckbox(hardware_tab,  "Row-Split", rowsplit_var, 5,0, tooltiptxt="Split rows across GPUs instead of splitting layers and KV across GPUs.\nUses the main GPU for small tensors and intermediate results. Speed may vary.")

    # threads
    makelabelentry(hardware_tab, "Threads:" , threads_var, 11, 50,tooltip="How many threads to use.\nRecommended value is your CPU core count, defaults are usually OK.")

    # hardware checkboxes
    hardware_boxes = {
        "Launch Browser": [launchbrowser, "Launches your default browser after model loading is complete"],
        "High Priority": [highpriority, "Increases the koboldcpp process priority.\nMay cause lag or slowdown instead. Not recommended."],
        "Disable MMAP": [disablemmap, "Avoids using mmap to load models if enabled"],
        "Use mlock": [usemlock, "Enables mlock, preventing the RAM used to load the model from being paged out."],
        "Debug Mode": [debugmode, "Enables debug mode, with extra info printed to the terminal."],
        "Keep Foreground": [keepforeground, "Bring KoboldCpp to the foreground every time there is a new generation."]
    }

    for idx, (name, properties) in enumerate(hardware_boxes.items()):
        makecheckbox(hardware_tab, name, properties[0], int(idx/2) + 30, idx % 2, tooltiptxt=properties[1])

    # blas thread specifier
    makelabelentry(hardware_tab, "BLAS threads:" , blas_threads_var, 14, 50,tooltip="How many threads to use during BLAS processing.\nIf left blank, uses same value as regular thread count.")
    # blas batch size
    makeslider(hardware_tab, "BLAS Batch Size:", blasbatchsize_text, blas_size_var, 0, 7, 16,width=200, set=5,tooltip="How many tokens to process at once per batch.\nLarger values use more memory.")
    blas_size_var.trace("w", changed_gpulayers_estimate)

    # force version
    makelabelentry(hardware_tab, "Force Version:" , version_var, 100, 50,tooltip="If the autodetected version is wrong, you can change it here.\nLeave as 0 for default.")
    ctk.CTkButton(hardware_tab , text = "Run Benchmark", command = guibench ).grid(row=110,column=0, stick="se", padx= 0, pady=2)


    runopts_var.trace('w', changerunmode)
    changerunmode(1,1,1)
    global runmode_untouched
    runmode_untouched = True

    # Tokens Tab
    tokens_tab = tabcontent["Tokens"]
    # tokens checkboxes
    smartcontextbox = makecheckbox(tokens_tab, "Use SmartContext", smartcontext, 1,tooltiptxt="Uses SmartContext. Now considered outdated and not recommended.\nCheck the wiki for more info.")
    makecheckbox(tokens_tab, "Use ContextShift", contextshift, 2,tooltiptxt="Uses Context Shifting to reduce reprocessing.\nRecommended. Check the wiki for more info.", command=togglectxshift)
    makecheckbox(tokens_tab, "Use FastForwarding", fastforward, 3,tooltiptxt="Use fast forwarding to recycle previous context (always reprocess if disabled).\nRecommended.", command=togglefastforward)

    # context size
    makeslider(tokens_tab, "Context Size:",contextsize_text, context_var, 0, len(contextsize_text)-1, 20, width=280, set=5,tooltip="What is the maximum context size to support. Model specific. You cannot exceed it.\nLarger contexts require more memory, and not all models support it.")
    context_var.trace("w", changed_gpulayers_estimate)

    customrope_scale_entry, customrope_scale_label = makelabelentry(tokens_tab, "RoPE Scale:", customrope_scale, row=23, padx=100, singleline=True, tooltip="For Linear RoPE scaling. RoPE frequency scale.")
    customrope_base_entry, customrope_base_label = makelabelentry(tokens_tab, "RoPE Base:", customrope_base, row=24, padx=100, singleline=True, tooltip="For NTK Aware Scaling. RoPE frequency base.")
    def togglerope(a,b,c):
        items = [customrope_scale_label, customrope_scale_entry,customrope_base_label, customrope_base_entry]
        for idx, item in enumerate(items):
            if customrope_var.get() == 1:
                item.grid()
            else:
                item.grid_remove()
    makecheckbox(tokens_tab,  "Custom RoPE Config", variable=customrope_var, row=22, command=togglerope,tooltiptxt="Override the default RoPE configuration with custom RoPE scaling.")
    makecheckbox(tokens_tab, "Use FlashAttention", flashattention, 28, command=toggleflashattn,  tooltiptxt="Enable flash attention for GGUF models.")
    noqkvlabel = makelabel(tokens_tab,"Requirments Not Met",31,0,"Requires FlashAttention ENABLED and ContextShift DISABLED.")
    noqkvlabel.configure(text_color="#ff5555")
    qkvslider,qkvlabel,qkvtitle = makeslider(tokens_tab, "Quantize KV Cache:", quantkv_text, quantkv_var, 0, 2, 30, set=0,tooltip="Enable quantization of KV cache.\nRequires FlashAttention and disables ContextShift.")

    togglerope(1,1,1)
    toggleflashattn(1,1,1)
    togglectxshift(1,1,1)

    # Model Tab
    model_tab = tabcontent["Model Files"]

    makefileentry(model_tab, "Text Model:", "Select GGUF or GGML Model File", model_var, 1,width=280,singlerow=True, onchoosefile=on_picked_model_file,tooltiptxt="Select a GGUF or GGML model file on disk to be loaded.")
    makefileentry(model_tab, "Text Lora:", "Select Lora File",lora_var, 3,width=280,singlerow=True,tooltiptxt="Select an optional GGML Text LoRA adapter to use.\nLeave blank to skip.")
    makefileentry(model_tab, "Lora Base:", "Select Lora Base File", lora_base_var, 5,width=280,singlerow=True,tooltiptxt="Select an optional F16 GGML Text LoRA base file to use.\nLeave blank to skip.")
    makefileentry(model_tab, "Vision mmproj:", "Select Vision mmproj File", mmproj_var, 7,width=280,singlerow=True,tooltiptxt="Select a mmproj file to use for vision models like LLaVA.\nLeave blank to skip.")
    makefileentry(model_tab, "Draft Model:", "Select Speculative Text Model File", draftmodel_var, 9,width=280,singlerow=True,tooltiptxt="Select a draft text model file to use for speculative decoding.\nLeave blank to skip.")
    makelabelentry(model_tab, "Draft Amount: ", draftamount_var, 11, 50,padx=100,singleline=True,tooltip="How many tokens to draft per chunk before verifying results")
    makefileentry(model_tab, "Preload Story:", "Select Preloaded Story File", preloadstory_var, 15,width=280,singlerow=True,tooltiptxt="Select an optional KoboldAI JSON savefile \nto be served on launch to any client.")
    makefileentry(model_tab, "ChatCompletions Adapter:", "Select ChatCompletions Adapter File", chatcompletionsadapter_var, 24, width=250, filetypes=[("JSON Adapter", "*.json")], tooltiptxt="Select an optional ChatCompletions Adapter JSON file to force custom instruct tags.")
    def pickpremadetemplate():
        initialDir = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'kcpp_adapters')
        initialDir = initialDir if os.path.isdir(initialDir) else None
        fnam = askopenfilename(title="Pick Premade ChatCompletions Adapter",filetypes=[("JSON Adapter", "*.json")], initialdir=initialDir)
        if fnam:
            chatcompletionsadapter_var.set(fnam)
    ctk.CTkButton(model_tab, 64, text="Pick Premade", command=pickpremadetemplate).grid(row=25, column=0, padx=322, stick="nw")

    mmproj_var.trace("w", gui_changed_modelfile)
    draftmodel_var.trace("w", gui_changed_modelfile)
    makecheckbox(model_tab, "Allow Launch Without Models", nomodel, 27, tooltiptxt="Allows running the WebUI with no model loaded.")

    # Network Tab
    network_tab = tabcontent["Network"]

    # interfaces
    makelabelentry(network_tab, "Port: ", port_var, 1, 150,tooltip="Select the port to host the KoboldCPP webserver.\n(Defaults to 5001)")
    makelabelentry(network_tab, "Host: ", host_var, 2, 150,tooltip="Select a specific host interface to bind to.\n(Defaults to all)")

    makecheckbox(network_tab, "Multiuser Mode", multiuser_var, 3,tooltiptxt="Allows requests by multiple different clients to be queued and handled in sequence.")
    makecheckbox(network_tab, "Remote Tunnel", remotetunnel, 3, 1,tooltiptxt="Creates a trycloudflare tunnel.\nAllows you to access koboldcpp from other devices over an internet URL.")
    makecheckbox(network_tab, "Quiet Mode", quietmode, 4,tooltiptxt="Prevents all generation related terminal output from being displayed.")
    makecheckbox(network_tab, "NoCertify Mode (Insecure)", nocertifymode, 4, 1,tooltiptxt="Allows insecure SSL connections. Use this if you have cert errors and need to bypass certificate restrictions.")
    makecheckbox(network_tab, "Shared Multiplayer", multiplayer_var, 5,tooltiptxt="Hosts a shared multiplayer session that others can join.")

    makefileentry(network_tab, "SSL Cert:", "Select SSL cert.pem file",ssl_cert_var, 7, width=200 ,filetypes=[("Unencrypted Certificate PEM", "*.pem")], singlerow=True, singlecol=False,tooltiptxt="Select your unencrypted .pem SSL certificate file for https.\nCan be generated with OpenSSL.")
    makefileentry(network_tab, "SSL Key:", "Select SSL key.pem file", ssl_key_var, 9, width=200, filetypes=[("Unencrypted Key PEM", "*.pem")], singlerow=True, singlecol=False, tooltiptxt="Select your unencrypted .pem SSL key file for https.\nCan be generated with OpenSSL.")
    makelabelentry(network_tab, "Password: ", password_var, 10, 200,tooltip="Enter a password required to use this instance.\nThis key will be required for all text endpoints.\nImage endpoints are not secured.")

    # Horde Tab
    horde_tab = tabcontent["Horde Worker"]
    makelabel(horde_tab, "Horde:", 18,0,"Settings for embedded AI Horde worker").grid(pady=10)

    horde_name_entry,  horde_name_label = makelabelentry(horde_tab, "Horde Model Name:", horde_name_var, 20, 180,tooltip="The model name to be displayed on the AI Horde.")
    horde_gen_entry,  horde_gen_label = makelabelentry(horde_tab, "Gen. Length:", horde_gen_var, 21, 50,tooltip="The maximum amount to generate per request \nthat this worker will accept jobs for.")
    horde_context_entry,  horde_context_label = makelabelentry(horde_tab, "Max Context:",horde_context_var, 22, 50,tooltip="The maximum context length \nthat this worker will accept jobs for.")
    horde_apikey_entry,  horde_apikey_label = makelabelentry(horde_tab, "API Key (If Embedded Worker):",horde_apikey_var, 23, 180,tooltip="Your AI Horde API Key that you have registered.")
    horde_workername_entry,  horde_workername_label = makelabelentry(horde_tab, "Horde Worker Name:",horde_workername_var, 24, 180,tooltip="Your worker's name to be displayed.")

    def togglehorde(a,b,c):
        horde_items = zip([horde_name_entry, horde_gen_entry, horde_context_entry, horde_apikey_entry, horde_workername_entry],
                          [horde_name_label, horde_gen_label, horde_context_label, horde_apikey_label, horde_workername_label])

        for item, label in horde_items:
            if usehorde_var.get() == 1:
                item.grid()
                label.grid()
            else:
                item.grid_remove()
                label.grid_remove()
        if usehorde_var.get()==1 and (horde_name_var.get()=="koboldcpp" or horde_name_var.get()=="") and model_var.get()!="":
            basefile = os.path.basename(model_var.get())
            horde_name_var.set(sanitize_string(os.path.splitext(basefile)[0]))

    makecheckbox(horde_tab, "Configure for Horde", usehorde_var, 19, command=togglehorde,tooltiptxt="Enable the embedded AI Horde worker.")
    togglehorde(1,1,1)

    # Image Gen Tab

    images_tab = tabcontent["Image Gen"]
    makefileentry(images_tab, "Stable Diffusion Model (safetensors/gguf):", "Select Stable Diffusion Model File", sd_model_var, 1, width=280, singlecol=True, filetypes=[("*.safetensors *.gguf","*.safetensors *.gguf")], tooltiptxt="Select a .safetensors or .gguf Stable Diffusion model file on disk to be loaded.")
    makelabelentry(images_tab, "Clamped Mode (Limit Resolution):", sd_clamped_var, 4, 50, padx=290,singleline=True,tooltip="Limit generation steps and resolution settings for shared use.\nSet to 0 to disable, otherwise value is the size limit (min 512px).")
    makelabelentry(images_tab, "Image Threads:" , sd_threads_var, 6, 50,padx=290,singleline=True,tooltip="How many threads to use during image generation.\nIf left blank, uses same value as threads.")
    sd_model_var.trace("w", gui_changed_modelfile)

    sdloritem1,sdloritem2,sdloritem3 = makefileentry(images_tab, "Image LoRA (Must be non-quant):", "Select SD lora file",sd_lora_var, 10, width=280, singlecol=True, filetypes=[("*.safetensors *.gguf", "*.safetensors *.gguf")],tooltiptxt="Select a .safetensors or .gguf SD LoRA model file to be loaded.")
    sdloritem4,sdloritem5 = makelabelentry(images_tab, "Image LoRA Multiplier:" , sd_loramult_var, 12, 50,padx=290,singleline=True,tooltip="What mutiplier value to apply the SD LoRA with.")
    def togglesdquant(a,b,c):
        if sd_quant_var.get()==1:
            sdloritem1.grid_remove()
            sdloritem2.grid_remove()
            sdloritem3.grid_remove()
            sdloritem4.grid_remove()
            sdloritem5.grid_remove()
        else:
            if not sdloritem1.grid_info() or not sdloritem2.grid_info() or not sdloritem3.grid_info() or not sdloritem4.grid_info() or not sdloritem5.grid_info():
                sdloritem1.grid()
                sdloritem2.grid()
                sdloritem3.grid()
                sdloritem4.grid()
                sdloritem5.grid()
    makecheckbox(images_tab, "Compress Weights (Saves Memory)", sd_quant_var, 8,command=togglesdquant,tooltiptxt="Quantizes the SD model weights to save memory. May degrade quality.")
    sd_quant_var.trace("w", changed_gpulayers_estimate)

    makefileentry(images_tab, "T5-XXL File:", "Select Optional T5-XXL model file (SD3 or flux)",sd_t5xxl_var, 14, width=280, singlerow=True, filetypes=[("*.safetensors *.gguf","*.safetensors *.gguf")],tooltiptxt="Select a .safetensors t5xxl file to be loaded.")
    makefileentry(images_tab, "Clip-L File:", "Select Optional Clip-L model file (SD3 or flux)",sd_clipl_var, 16, width=280, singlerow=True, filetypes=[("*.safetensors *.gguf","*.safetensors *.gguf")],tooltiptxt="Select a .safetensors t5xxl file to be loaded.")
    makefileentry(images_tab, "Clip-G File:", "Select Optional Clip-G model file (SD3)",sd_clipg_var, 18, width=280, singlerow=True, filetypes=[("*.safetensors *.gguf","*.safetensors *.gguf")],tooltiptxt="Select a .safetensors t5xxl file to be loaded.")

    sdvaeitem1,sdvaeitem2,sdvaeitem3 = makefileentry(images_tab, "Image VAE:", "Select Optional SD VAE file",sd_vae_var, 20, width=280, singlerow=True, filetypes=[("*.safetensors *.gguf", "*.safetensors *.gguf")],tooltiptxt="Select a .safetensors or .gguf SD VAE file to be loaded.")
    def toggletaesd(a,b,c):
        if sd_vaeauto_var.get()==1:
            sdvaeitem1.grid_remove()
            sdvaeitem2.grid_remove()
            sdvaeitem3.grid_remove()
        else:
            if not sdvaeitem1.grid_info() or not sdvaeitem2.grid_info() or not sdvaeitem3.grid_info():
                sdvaeitem1.grid()
                sdvaeitem2.grid()
                sdvaeitem3.grid()
    makecheckbox(images_tab, "Use TAE SD (AutoFix Broken VAE)", sd_vaeauto_var, 22,command=toggletaesd,tooltiptxt="Replace VAE with TAESD. May fix bad VAE.")

    # audio tab
    audio_tab = tabcontent["Audio"]
    makefileentry(audio_tab, "Whisper Model (Speech-To-Text):", "Select Whisper .bin Model File", whisper_model_var, 1, width=280, filetypes=[("*.bin","*.bin")], tooltiptxt="Select a Whisper .bin model file on disk to be loaded.")
    whisper_model_var.trace("w", gui_changed_modelfile)

    def kcpp_export_template():
        nonlocal kcpp_exporting_template
        kcpp_exporting_template = True
        export_vars()
        kcpp_exporting_template = False
        savdict = json.loads(json.dumps(args.__dict__))
        file_type = [("KoboldCpp LaunchTemplate", "*.kcppt")]
        #remove blacklisted fields
        savdict["istemplate"] = True
        savdict["gpulayers"] = -1
        savdict["threads"] = -1
        savdict["hordekey"] = ""
        savdict["hordeworkername"] = ""
        savdict["sdthreads"] = 0
        savdict["password"] = None
        savdict["nommap"] = False
        savdict["usemlock"] = False
        savdict["debugmode"] = 0
        savdict["ssl"] = None
        savdict["useclblast"] = None
        savdict["usecublas"] = None
        savdict["usevulkan"] = None
        savdict["tensor_split"] = None
        savdict["config"] = None
        filename = asksaveasfile(filetypes=file_type, defaultextension=file_type)
        if filename == None:
            return
        file = open(str(filename.name), 'a')
        file.write(json.dumps(savdict))
        file.close()
        pass

    # extra tab
    extra_tab = tabcontent["Extra"]
    makelabel(extra_tab, "Unpack KoboldCpp to a local directory to modify its files.", 1, 0)
    makelabel(extra_tab, "You can also launch via koboldcpp.py for faster startup.", 2, 0)
    ctk.CTkButton(extra_tab , text = "Unpack KoboldCpp To Folder", command = unpack_to_dir ).grid(row=3,column=0, stick="w", padx= 8, pady=2)
    makelabel(extra_tab, "Export as launcher .kcppt template (Expert Only)", 4, 0,tooltiptxt="Creates a KoboldCpp launch template for others to use.\nEmbeds JSON files directly into exported file when saving.\nWhen loaded, forces the backend to be automatically determined.\nWarning! Not recommended for beginners!")
    ctk.CTkButton(extra_tab , text = "Generate LaunchTemplate", command = kcpp_export_template ).grid(row=5,column=0, stick="w", padx= 8, pady=2)

    # launch
    def guilaunch():
        if model_var.get() == "" and sd_model_var.get() == "" and whisper_model_var.get() == "" and nomodel.get()!=1:
            tmp = askopenfilename(title="Select ggml model .bin or .gguf file")
            model_var.set(tmp)
        nonlocal nextstate
        nextstate = 1
        root.withdraw()
        root.quit()
        pass

    def export_vars():
        nonlocal kcpp_exporting_template
        args.threads = int(threads_var.get())
        args.usemlock   = usemlock.get() == 1
        args.debugmode  = debugmode.get()
        args.launch     = launchbrowser.get()==1
        args.highpriority = highpriority.get()==1
        args.nommap = disablemmap.get()==1
        args.smartcontext = smartcontext.get()==1
        args.flashattention = flashattention.get()==1
        args.noshift = contextshift.get()==0
        args.nofastforward = fastforward.get()==0
        args.remotetunnel = remotetunnel.get()==1
        args.foreground = keepforeground.get()==1
        args.quiet = quietmode.get()==1
        args.nocertify = nocertifymode.get()==1
        args.nomodel = nomodel.get()==1
        if contextshift.get()==0 and flashattention.get()==1:
            args.quantkv = quantkv_var.get()
        else:
            args.quantkv = 0

        gpuchoiceidx = 0
        args.usecpu = False
        args.usevulkan = None
        args.usecublas = None
        args.useclblast = None
        args.noavx2 = False
        if gpu_choice_var.get()!="All":
            gpuchoiceidx = int(gpu_choice_var.get())-1
        if runopts_var.get() == "Use CLBlast" or runopts_var.get() == "Use CLBlast (Old CPU)":
            args.useclblast = [[0,0], [1,0], [0,1], [1,1]][gpuchoiceidx]
            if runopts_var.get() == "CUse CLBlast (Old CPU)":
                args.noavx2 = True
        if runopts_var.get() == "Use CuBLAS" or runopts_var.get() == "Use hipBLAS (ROCm)":
            if gpu_choice_var.get()=="All":
                args.usecublas = ["lowvram"] if lowvram_var.get() == 1 else ["normal"]
            else:
                args.usecublas = ["lowvram",str(gpuchoiceidx)] if lowvram_var.get() == 1 else ["normal",str(gpuchoiceidx)]
            if mmq_var.get()==1:
                args.usecublas.append("mmq")
            if rowsplit_var.get()==1:
                args.usecublas.append("rowsplit")
        if runopts_var.get() == "Use Vulkan" or runopts_var.get() == "Use Vulkan (Old CPU)":
            if gpu_choice_var.get()=="All":
                args.usevulkan = []
            else:
                args.usevulkan = [int(gpuchoiceidx)]
            if runopts_var.get() == "Use Vulkan (Old CPU)":
                args.noavx2 = True
        if gpulayers_var.get():
            args.gpulayers = int(gpulayers_var.get())
        if runopts_var.get()=="Use CPU":
            args.usecpu = True
        if runopts_var.get()=="Use CPU (Old CPU)":
            args.noavx2 = True
        if runopts_var.get()=="Failsafe Mode (Old CPU)":
            args.noavx2 = True
            args.usecpu = True
            args.nommap = True
        if tensor_split_str_vars.get()!="":
            tssv = tensor_split_str_vars.get()
            if "," in tssv:
                args.tensor_split = [float(x) for x in tssv.split(",")]
            else:
                args.tensor_split = [float(x) for x in tssv.split(" ")]

        args.blasthreads = None if blas_threads_var.get()=="" else int(blas_threads_var.get())

        args.blasbatchsize = int(blasbatchsize_values[int(blas_size_var.get())])
        args.forceversion = 0 if version_var.get()=="" else int(version_var.get())

        args.contextsize = int(contextsize_text[context_var.get()])

        if customrope_var.get()==1:
            args.ropeconfig = [float(customrope_scale.get()),float(customrope_base.get())]

        args.chatcompletionsadapter = None if chatcompletionsadapter_var.get() == "" else chatcompletionsadapter_var.get()
        try:
            if kcpp_exporting_template and isinstance(args.chatcompletionsadapter, str) and args.chatcompletionsadapter!="" and os.path.exists(args.chatcompletionsadapter):
                print(f"Embedding chat completions adapter...")   # parse and save embedded preload story
                with open(args.chatcompletionsadapter, 'r') as f:
                    args.chatcompletionsadapter = json.load(f)
        except Exception as ex2:
            pass

        args.model_param = None if model_var.get() == "" else model_var.get()
        args.lora = None if lora_var.get() == "" else ([lora_var.get()] if lora_base_var.get()=="" else [lora_var.get(), lora_base_var.get()])
        args.preloadstory = None if preloadstory_var.get() == "" else preloadstory_var.get()
        try:
            if kcpp_exporting_template and isinstance(args.preloadstory, str) and args.preloadstory!="" and os.path.exists(args.preloadstory):
                print(f"Embedding preload story...")   # parse and save embedded preload story
                with open(args.preloadstory, 'r') as f:
                    args.preloadstory = json.load(f)
        except Exception as ex2:
            pass
        args.mmproj = None if mmproj_var.get() == "" else mmproj_var.get()
        args.draftmodel = None if draftmodel_var.get() == "" else draftmodel_var.get()
        args.draftamount = int(draftamount_var.get()) if draftamount_var.get()!="" else default_draft_amount

        args.ssl = None if (ssl_cert_var.get() == "" or ssl_key_var.get() == "") else ([ssl_cert_var.get(), ssl_key_var.get()])
        args.password = None if (password_var.get() == "") else (password_var.get())

        args.port_param = defaultport if port_var.get()=="" else int(port_var.get())
        args.host = host_var.get()
        args.multiuser = multiuser_var.get()
        args.multiplayer = (multiplayer_var.get()==1)

        if usehorde_var.get() != 0:
            args.hordemodelname = horde_name_var.get()
            args.hordegenlen = int(horde_gen_var.get())
            args.hordemaxctx = int(horde_context_var.get())
            if horde_apikey_var.get()!="" and horde_workername_var.get()!="":
                args.hordekey = horde_apikey_var.get()
                args.hordeworkername = horde_workername_var.get()

        if sd_model_var.get() != "":
            args.sdmodel = sd_model_var.get()

        args.sdthreads = (0 if sd_threads_var.get()=="" else int(sd_threads_var.get()))
        args.sdclamped = (0 if int(sd_clamped_var.get())<=0 else int(sd_clamped_var.get()))
        if sd_vaeauto_var.get()==1:
            args.sdvaeauto = True
            args.sdvae = ""
        else:
            args.sdvaeauto = False
            args.sdvae = ""
            if sd_vae_var.get() != "":
                args.sdvae = sd_vae_var.get()
        if sd_t5xxl_var.get() != "":
            args.sdt5xxl = sd_t5xxl_var.get()
        if sd_clipl_var.get() != "":
            args.sdclipl = sd_clipl_var.get()
        if sd_clipg_var.get() != "":
            args.sdclipg = sd_clipg_var.get()
        if sd_quant_var.get()==1:
            args.sdquant = True
            args.sdlora = ""
        else:
            if sd_lora_var.get() != "":
                args.sdlora = sd_lora_var.get()
                args.sdloramult = float(sd_loramult_var.get())
            else:
                args.sdlora = ""

        if whisper_model_var.get() != "":
            args.whispermodel = whisper_model_var.get()

    def import_vars(dict):
        global importvars_in_progress
        importvars_in_progress = True
        dict = convert_outdated_args(dict)

        if "threads" in dict:
            threads_var.set(dict["threads"])
        usemlock.set(1 if "usemlock" in dict and dict["usemlock"] else 0)
        if "debugmode" in dict:
            debugmode.set(dict["debugmode"])
        launchbrowser.set(1 if "launch" in dict and dict["launch"] else 0)
        highpriority.set(1 if "highpriority" in dict and dict["highpriority"] else 0)
        disablemmap.set(1 if "nommap" in dict and dict["nommap"] else 0)
        smartcontext.set(1 if "smartcontext" in dict and dict["smartcontext"] else 0)
        flashattention.set(1 if "flashattention" in dict and dict["flashattention"] else 0)
        contextshift.set(0 if "noshift" in dict and dict["noshift"] else 1)
        fastforward.set(0 if "nofastforward" in dict and dict["nofastforward"] else 1)
        remotetunnel.set(1 if "remotetunnel" in dict and dict["remotetunnel"] else 0)
        keepforeground.set(1 if "foreground" in dict and dict["foreground"] else 0)
        quietmode.set(1 if "quiet" in dict and dict["quiet"] else 0)
        nocertifymode.set(1 if "nocertify" in dict and dict["nocertify"] else 0)
        nomodel.set(1 if "nomodel" in dict and dict["nomodel"] else 0)
        if "quantkv" in dict:
            quantkv_var.set(dict["quantkv"])
        if "useclblast" in dict and dict["useclblast"]:
            if "noavx2" in dict and dict["noavx2"]:
                if clblast_noavx2_option is not None:
                    runopts_var.set(clblast_noavx2_option)
                    gpu_choice_var.set(str(["0 0", "1 0", "0 1", "1 1"].index(str(dict["useclblast"][0]) + " " + str(dict["useclblast"][1])) + 1))
            else:
                if clblast_option is not None:
                    runopts_var.set(clblast_option)
                    gpu_choice_var.set(str(["0 0", "1 0", "0 1", "1 1"].index(str(dict["useclblast"][0]) + " " + str(dict["useclblast"][1])) + 1))
        elif "usecublas" in dict and dict["usecublas"]:
            if cublas_option is not None or hipblas_option is not None:
                if cublas_option:
                    runopts_var.set(cublas_option)
                elif hipblas_option:
                    runopts_var.set(hipblas_option)
                lowvram_var.set(1 if "lowvram" in dict["usecublas"] else 0)
                mmq_var.set(1 if "mmq" in dict["usecublas"] else 0)
                rowsplit_var.set(1 if "rowsplit" in dict["usecublas"] else 0)
                gpu_choice_var.set("All")
                for g in range(4):
                    if str(g) in dict["usecublas"]:
                        gpu_choice_var.set(str(g+1))
                        break
        elif "usevulkan" in dict and dict['usevulkan'] is not None:
            if "noavx2" in dict and dict["noavx2"]:
                if vulkan_noavx2_option is not None:
                    runopts_var.set(vulkan_noavx2_option)
                    gpu_choice_var.set("All")
                    for opt in range(0,4):
                        if opt in dict["usevulkan"]:
                            gpu_choice_var.set(str(opt+1))
                            break
            else:
                if vulkan_option is not None:
                    runopts_var.set(vulkan_option)
                    gpu_choice_var.set("All")
                    for opt in range(0,4):
                        if opt in dict["usevulkan"]:
                            gpu_choice_var.set(str(opt+1))
                            break

        elif  "noavx2" in dict and "usecpu" in dict and dict["usecpu"] and dict["noavx2"]:
            if failsafe_option is not None:
                runopts_var.set(failsafe_option)
        elif "noavx2" in dict and dict["noavx2"]:
            if noavx2_option is not None:
                runopts_var.set(noavx2_option)
        elif "usecpu" in dict and dict["usecpu"]:
            if default_option is not None:
                runopts_var.set(default_option)
        if "gpulayers" in dict and dict["gpulayers"]:
            gpulayers_var.set(dict["gpulayers"])
        else:
            gpulayers_var.set("0")
        if "tensor_split" in dict and dict["tensor_split"]:
            tssep = ','.join(map(str, dict["tensor_split"]))
            tensor_split_str_vars.set(tssep)
        if "blasthreads" in dict and dict["blasthreads"]:
            blas_threads_var.set(str(dict["blasthreads"]))
        else:
            blas_threads_var.set("")
        if "contextsize" in dict and dict["contextsize"]:
            context_var.set(contextsize_text.index(str(dict["contextsize"])))
        if "ropeconfig" in dict and dict["ropeconfig"] and len(dict["ropeconfig"])>1:
            if dict["ropeconfig"][0]>0:
                customrope_var.set(1)
                customrope_scale.set(str(dict["ropeconfig"][0]))
                customrope_base.set(str(dict["ropeconfig"][1]))
            else:
                customrope_var.set(0)

        if "blasbatchsize" in dict and dict["blasbatchsize"]:
            blas_size_var.set(blasbatchsize_values.index(str(dict["blasbatchsize"])))

        version_var.set(str(dict["forceversion"]) if ("forceversion" in dict and dict["forceversion"]) else "0")
        model_var.set(dict["model_param"] if ("model_param" in dict and dict["model_param"]) else "")

        lora_var.set("")
        lora_base_var.set("")
        if "lora" in dict and dict["lora"]:
            if len(dict["lora"]) > 1:
                lora_var.set(dict["lora"][0])
                lora_base_var.set(dict["lora"][1])
            else:
                lora_var.set(dict["lora"][0])

        mmproj_var.set(dict["mmproj"] if ("mmproj" in dict and dict["mmproj"]) else "")
        draftmodel_var.set(dict["draftmodel"] if ("draftmodel" in dict and dict["draftmodel"]) else "")
        if "draftamount" in dict:
            draftamount_var.set(dict["draftamount"])

        ssl_cert_var.set("")
        ssl_key_var.set("")
        if "ssl" in dict and dict["ssl"]:
            if len(dict["ssl"]) == 2:
                ssl_cert_var.set(dict["ssl"][0])
                ssl_key_var.set(dict["ssl"][1])

        password_var.set(dict["password"] if ("password" in dict and dict["password"]) else "")
        preloadstory_var.set(dict["preloadstory"] if ("preloadstory" in dict and dict["preloadstory"]) else "")
        chatcompletionsadapter_var.set(dict["chatcompletionsadapter"] if ("chatcompletionsadapter" in dict and dict["chatcompletionsadapter"]) else "")
        port_var.set(dict["port_param"] if ("port_param" in dict and dict["port_param"]) else defaultport)
        host_var.set(dict["host"] if ("host" in dict and dict["host"]) else "")
        multiuser_var.set(dict["multiuser"] if ("multiuser" in dict) else 1)
        multiplayer_var.set(dict["multiplayer"] if ("multiplayer" in dict) else 0)

        horde_name_var.set(dict["hordemodelname"] if ("hordemodelname" in dict and dict["hordemodelname"]) else "koboldcpp")
        horde_context_var.set(dict["hordemaxctx"] if ("hordemaxctx" in dict and dict["hordemaxctx"]) else maxhordectx)
        horde_gen_var.set(dict["hordegenlen"] if ("hordegenlen" in dict and dict["hordegenlen"]) else maxhordelen)
        horde_apikey_var.set(dict["hordekey"] if ("hordekey" in dict and dict["hordekey"]) else "")
        horde_workername_var.set(dict["hordeworkername"] if ("hordeworkername" in dict and dict["hordeworkername"]) else "")
        usehorde_var.set(1 if ("hordekey" in dict and dict["hordekey"]) else 0)

        sd_model_var.set(dict["sdmodel"] if ("sdmodel" in dict and dict["sdmodel"]) else "")
        sd_clamped_var.set(int(dict["sdclamped"]) if ("sdclamped" in dict and dict["sdclamped"]) else 0)
        sd_threads_var.set(str(dict["sdthreads"]) if ("sdthreads" in dict and dict["sdthreads"]) else str(default_threads))
        sd_quant_var.set(1 if ("sdquant" in dict and dict["sdquant"]) else 0)
        sd_vae_var.set(dict["sdvae"] if ("sdvae" in dict and dict["sdvae"]) else "")
        sd_t5xxl_var.set(dict["sdt5xxl"] if ("sdt5xxl" in dict and dict["sdt5xxl"]) else "")
        sd_clipl_var.set(dict["sdclipl"] if ("sdclipl" in dict and dict["sdclipl"]) else "")
        sd_clipg_var.set(dict["sdclipg"] if ("sdclipg" in dict and dict["sdclipg"]) else "")
        sd_vaeauto_var.set(1 if ("sdvaeauto" in dict and dict["sdvaeauto"]) else 0)
        sd_lora_var.set(dict["sdlora"] if ("sdlora" in dict and dict["sdlora"]) else "")
        sd_loramult_var.set(str(dict["sdloramult"]) if ("sdloramult" in dict and dict["sdloramult"]) else "1.0")

        whisper_model_var.set(dict["whispermodel"] if ("whispermodel" in dict and dict["whispermodel"]) else "")

        importvars_in_progress = False
        gui_changed_modelfile()
        if "istemplate" in dict and dict["istemplate"]:
            auto_set_backend_gui(True)

    def save_config_gui():
        nonlocal kcpp_exporting_template
        kcpp_exporting_template = False
        export_vars()
        savdict = json.loads(json.dumps(args.__dict__))
        file_type = [("KoboldCpp Settings", "*.kcpps")]
        filename = asksaveasfile(filetypes=file_type, defaultextension=file_type)
        if filename == None: return
        file = open(str(filename.name), 'a')
        file.write(json.dumps(savdict))
        file.close()
        pass

    def load_config_gui(): #this is used to populate the GUI with a config file, whereas load_config_cli simply overwrites cli args
        file_type = [("KoboldCpp Settings", "*.kcpps *.kcppt")]
        global runmode_untouched
        filename = askopenfilename(filetypes=file_type, defaultextension=file_type, initialdir=None)
        if not filename or filename=="":
            return
        runmode_untouched = False
        with open(filename, 'r') as f:
            dict = json.load(f)
            import_vars(dict)
        pass

    def display_help():
        try:
            import webbrowser as wb
            wb.open("https://github.com/LostRuins/koboldcpp/wiki")
        except:
            print("Cannot launch help in browser.")
    def display_help_models():
        try:
            import webbrowser as wb
            wb.open("https://github.com/LostRuins/koboldcpp/wiki#what-models-does-koboldcpp-support-what-architectures-are-supported")
        except:
            print("Cannot launch help in browser.")
    def display_updates():
        try:
            import webbrowser as wb
            wb.open("https://github.com/LostRuins/koboldcpp/releases/latest")
        except:
            print("Cannot launch updates in browser.")

    ctk.CTkButton(tabs , text = "Launch", fg_color="#2f8d3c", hover_color="#2faa3c", command = guilaunch, width=80, height = 35 ).grid(row=1,column=1, stick="se", padx= 25, pady=5)

    ctk.CTkButton(tabs , text = "Update", fg_color="#9900cc", hover_color="#aa11dd", command = display_updates, width=90, height = 35 ).grid(row=1,column=0, stick="sw", padx= 5, pady=5)
    ctk.CTkButton(tabs , text = "Save", fg_color="#084a66", hover_color="#085a88", command = save_config_gui, width=60, height = 35 ).grid(row=1,column=1, stick="sw", padx= 5, pady=5)
    ctk.CTkButton(tabs , text = "Load", fg_color="#084a66", hover_color="#085a88", command = load_config_gui, width=60, height = 35 ).grid(row=1,column=1, stick="sw", padx= 70, pady=5)
    ctk.CTkButton(tabs , text = "Help", fg_color="#992222", hover_color="#bb3333", command = display_help, width=60, height = 35 ).grid(row=1,column=1, stick="sw", padx= 135, pady=5)

    # start a thread that tries to get actual gpu names and layer counts
    gpuinfo_thread = threading.Thread(target=auto_set_backend_gui)
    gpuinfo_thread.start() #submit job in new thread so nothing is waiting

    if args.showgui:
        if isinstance(args, argparse.Namespace):
            dict = vars(args)
            import_vars(dict)

    # runs main loop until closed or launch clicked
    root.mainloop()

    if nextstate==0:
        exitcounter = 999
        print("Exiting by user request.")
        sys.exit(0)
    else:
        # processing vars
        kcpp_exporting_template = False
        export_vars()

        if not args.model_param and not args.sdmodel and not args.whispermodel and not args.nomodel:
            exitcounter = 999
            print("")
            time.sleep(0.5)
            if guimode:
                givehelp = show_gui_yesnobox("No Model Loaded","No text or image model file was selected. Cannot continue.\n\nDo you want help finding a GGUF model?")
                if givehelp == 'yes':
                    display_help_models()
            else:
                print("No text or image model file was selected. Cannot continue.", flush=True)
            time.sleep(2)
            sys.exit(2)

def show_gui_msgbox(title,message):
    print(title + ": " + message, flush=True)
    try:
        from tkinter import messagebox
        import tkinter as tk
        root = tk.Tk()
        root.attributes("-alpha", 0)
        messagebox.showerror(title=title, message=message)
        root.withdraw()
        root.quit()
    except Exception as ex2:
        pass

def show_gui_yesnobox(title,message):
    print(title + ": " + message, flush=True)
    try:
        from tkinter import messagebox
        import tkinter as tk
        root = tk.Tk()
        root.attributes("-alpha", 0)
        result = messagebox.askquestion(title=title, message=message,icon='error')
        root.withdraw()
        root.quit()
        return result
    except Exception as ex2:
        return False
        pass

def print_with_time(txt):
    print(f"{datetime.now().strftime('[%H:%M:%S]')} " + txt, flush=True)

def make_url_request(url, data, method='POST', headers={}):
    import urllib.request, ssl
    global nocertify
    try:
        request = None
        ssl_cert_dir = os.environ.get('SSL_CERT_DIR')
        if not ssl_cert_dir and not nocertify and os.name != 'nt':
            os.environ['SSL_CERT_DIR'] = '/etc/ssl/certs'
        ssl_context = ssl.create_default_context()
        if nocertify:
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
        if method=='POST':
            json_payload = json.dumps(data).encode('utf-8')
            request = urllib.request.Request(url, data=json_payload, headers=headers, method=method)
            request.add_header('content-type', 'application/json')
        else:
            request = urllib.request.Request(url, headers=headers, method=method)
        response_data = ""
        with urllib.request.urlopen(request,context=ssl_context,timeout=300) as response:
            response_data = response.read().decode('utf-8',"ignore")
            json_response = json.loads(response_data)
            return json_response
    except urllib.error.HTTPError as e:
        try:
            errmsg = e.read().decode('utf-8',"ignore")
            print_with_time(f"Error: {e} - {errmsg}")
        except Exception as e:
            print_with_time(f"Error: {e}")
        return None
    except Exception as e:
        print_with_time(f"Error: {e} - {response_data}")
        return None

#A very simple and stripped down embedded horde worker with no dependencies
def run_horde_worker(args, api_key, worker_name):
    import random
    global friendlymodelname, maxhordectx, maxhordelen, exitcounter, punishcounter, modelbusy, session_starttime, sslvalid
    httpsaffix = ("https" if sslvalid else "http")
    epurl = f"{httpsaffix}://localhost:{args.port}"
    if args.host!="":
        epurl = f"{httpsaffix}://{args.host}:{args.port}"

    def submit_completed_generation(url, jobid, sessionstart, submit_dict):
        global exitcounter, punishcounter, session_kudos_earned, session_jobs, rewardcounter
        reply = make_url_request_horde(url, submit_dict)
        if not reply:
            punishcounter += 1
            print_with_time(f"Error, Job submit failed.")
        else:
            reward = reply["reward"]
            session_kudos_earned += reward
            session_jobs += 1
            curtime = datetime.now()
            elapsedtime=curtime-sessionstart
            hrs = int(elapsedtime.total_seconds()) // 3600
            mins = elapsedtime.seconds // 60 % 60
            secs = elapsedtime.seconds % 60
            elapsedtimestr = f"{hrs:03d}h:{mins:02d}m:{secs:02d}s"
            earnrate = session_kudos_earned/(elapsedtime.total_seconds()/3600)
            print_with_time(f'Submitted {jobid} and earned {reward:.0f} kudos\n[Total:{session_kudos_earned:.0f} kudos, Time:{elapsedtimestr}, Jobs:{session_jobs}, EarnRate:{earnrate:.0f} kudos/hr]')
            rewardcounter += 1
            if rewardcounter > 50:
                rewardcounter = 0
                if exitcounter > 1:
                    exitcounter -= 1

    def make_url_request_horde(url, data, method='POST',addmykey=False):
        global password
        headers = headers = {"apikey": api_key,'User-Agent':'KoboldCppEmbeddedWorkerV2','Client-Agent':'KoboldCppEmbedWorker:2'}
        if addmykey and password!="":
            headers["Authorization"] = f"Bearer {password}"
        ret = make_url_request(url, data, method, headers)
        if not ret:
            print("Make sure your Horde API key and worker name is valid!")
        return ret

    current_id = None
    current_payload = None
    current_generation = None
    session_starttime = datetime.now()
    sleepy_counter = 0 #if this exceeds a value, worker becomes sleepy (slower)
    exitcounter = 0
    print(f"===\nEmbedded Horde Worker '{worker_name}' Starting...\n(To use your own Horde Bridge/Scribe worker instead, don't set your API key)\n")
    BRIDGE_AGENT = f"KoboldCppEmbedWorker:2:https://github.com/LostRuins/koboldcpp"
    cluster = "https://aihorde.net"
    while exitcounter < 10:
        time.sleep(3)
        readygo = make_url_request_horde(f'{epurl}/api/v1/info/version', None,'GET',addmykey=True)
        if readygo:
            print_with_time(f"Embedded Horde Worker '{worker_name}' is started.")
            break

    while exitcounter < 10:
        currentjob_attempts = 0
        current_generation = None

        if punishcounter >= 5:
            punishcounter = 0
            exitcounter += 1
            if exitcounter < 10:
                penaltytime = (2 ** exitcounter)
                print_with_time(f"Horde Worker Paused for {penaltytime} min - Too many errors. It will resume automatically, but you should restart it.")
                print_with_time(f"Caution: Too many failed jobs may lead to entering maintenance mode.")
                time.sleep(60 * penaltytime)
            else:
                 print_with_time(f"Horde Worker Exit limit reached, too many errors.")

        global last_non_horde_req_time
        sec_since_non_horde = time.time() - last_non_horde_req_time
        no_recent_local_usage = sec_since_non_horde>20
        if not no_recent_local_usage:
            #print_with_time(f"Recent Local Usage - Horde Worker Waiting...")
            time.sleep(1)
            continue

        #first, make sure we are not generating
        if modelbusy.locked():
            time.sleep(0.2)
            continue

        #pop new request
        gen_dict = {
            "name": worker_name,
            "models": [friendlymodelname],
            "max_length": maxhordelen,
            "max_context_length": maxhordectx,
            "priority_usernames": [],
            "softprompts": [],
            "bridge_agent": BRIDGE_AGENT,
        }
        pop = make_url_request_horde(f'{cluster}/api/v2/generate/text/pop',gen_dict)
        if not pop:
            punishcounter += 1
            print_with_time(f"Failed to fetch job from {cluster}. Waiting 10 seconds...")
            time.sleep(10)
            continue
        if not pop["id"]:
            slp = (1 if sleepy_counter<10 else (2 if sleepy_counter<25 else 3))
            time.sleep(slp)
            sleepy_counter += 1
            if sleepy_counter==20:
                print_with_time(f"No recent jobs, entering low power mode...")
            continue

        sleepy_counter = 0
        current_id = pop['id']
        current_payload = pop['payload']
        print(f"") #empty newline
        print_with_time(f"Job received from {cluster} for {current_payload.get('max_length',80)} tokens and {current_payload.get('max_context_length',1024)} max context. Starting generation...")

        #do gen
        while exitcounter < 10:
            if not modelbusy.locked():
                #horde gets a genkey to avoid KCPP overlap
                current_payload['genkey'] = f"HORDEREQ_{random.randint(100, 999)}"
                current_generation = make_url_request_horde(f'{epurl}/api/v1/generate', current_payload, method='POST',addmykey=True)
                if current_generation:
                    break
                else:
                    currentjob_attempts += 1
                    if currentjob_attempts>5:
                        break

            print_with_time(f"Server Busy - Not ready to generate...")
            time.sleep(5)

        #submit reply
        print(f"") #empty newline
        if current_generation:
            submit_dict = {
                "id": current_id,
                "generation": current_generation["results"][0]["text"],
                "state": "ok"
            }
            submiturl = cluster + '/api/v2/generate/text/submit'
            submit_thread = threading.Thread(target=submit_completed_generation, args=(submiturl, current_id, session_starttime, submit_dict))
            submit_thread.start() #submit job in new thread so nothing is waiting
        else:
            print_with_time(f"Error, Abandoned current job due to errors. Getting new job.")
        current_id = None
        current_payload = None
        time.sleep(0.1)

    if exitcounter<100:
        print_with_time(f"Horde Worker Shutdown - Too many errors.")
    else:
        print_with_time(f"Horde Worker Shutdown - Server Closing.")
    exitcounter = 999
    time.sleep(3)
    sys.exit(2)

def convert_outdated_args(args):
    dict = args
    if isinstance(args, argparse.Namespace):
        dict = vars(args)

    global using_outdated_flags
    using_outdated_flags = False
    if "sdconfig" in dict and dict["sdconfig"] and len(dict["sdconfig"])>0:
        using_outdated_flags = True
        dict["sdmodel"] = dict["sdconfig"][0]
        if dict["sdconfig"] and len(dict["sdconfig"]) > 1:
            dict["sdclamped"] = 512
        if dict["sdconfig"] and len(dict["sdconfig"]) > 2:
            dict["sdthreads"] = int(dict["sdconfig"][2])
        if dict["sdconfig"] and len(dict["sdconfig"]) > 3:
            dict["sdquant"] = (True if dict["sdconfig"][3]=="quant" else False)
    if "hordeconfig" in dict and dict["hordeconfig"] and dict["hordeconfig"][0]!="":
        using_outdated_flags = True
        dict["hordemodelname"] = dict["hordeconfig"][0]
        if len(dict["hordeconfig"]) > 1:
            dict["hordegenlen"] = int(dict["hordeconfig"][1])
        if len(dict["hordeconfig"]) > 2:
            dict["hordemaxctx"] = int(dict["hordeconfig"][2])
        if len(dict["hordeconfig"]) > 4:
            dict["hordekey"] = dict["hordeconfig"][3]
            dict["hordeworkername"] = dict["hordeconfig"][4]
    if "noblas" in dict and dict["noblas"]:
        dict["usecpu"] = True

    check_deprecation_warning()
    return args

def check_deprecation_warning():
    # slightly naggy warning to encourage people to switch to new flags
    # if you want you can remove this at your own risk,
    # but i am not going to troubleshoot or provide support for deprecated flags.
    global using_outdated_flags
    if using_outdated_flags:
        print(f"\n=== !!! IMPORTANT WARNING !!! ===")
        print("You are using one or more OUTDATED config files or launch flags!")
        print("The flags --hordeconfig and --sdconfig have been DEPRECATED, and MAY be REMOVED in future!")
        print("They will still work for now, but you SHOULD switch to the updated flags instead, to avoid future issues!")
        print("New flags are: --hordemodelname --hordeworkername --hordekey --hordemaxctx --hordegenlen --sdmodel --sdthreads --sdquant --sdclamped")
        print("For more information on these flags, please check --help")
        print(">>> If you are using the GUI launcher, simply re-saving your config again will get rid of this warning.")
        print("=== !!! IMPORTANT WARNING !!! ===\n")



def setuptunnel(has_sd):
    # This script will help setup a cloudflared tunnel for accessing KoboldCpp over the internet
    # It should work out of the box on both linux and windows
    try:
        import subprocess, re
        global sslvalid
        httpsaffix = ("https" if sslvalid else "http")
        def run_tunnel():
            tunnelproc = None
            tunneloutput = ""
            tunnelrawlog = ""
            time.sleep(0.2)
            if os.name == 'nt':
                print("Starting Cloudflare Tunnel for Windows, please wait...", flush=True)
                tunnelproc = subprocess.Popen(f"cloudflared.exe tunnel --url {httpsaffix}://localhost:{args.port}", text=True, encoding='utf-8', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            elif sys.platform=="darwin":
                print("Starting Cloudflare Tunnel for MacOS, please wait...", flush=True)
                tunnelproc = subprocess.Popen(f"./cloudflared tunnel --url {httpsaffix}://localhost:{args.port}", text=True, encoding='utf-8', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            else:
                print("Starting Cloudflare Tunnel for Linux, please wait...", flush=True)
                tunnelproc = subprocess.Popen(f"./cloudflared-linux-amd64 tunnel --url {httpsaffix}://localhost:{args.port}", text=True, encoding='utf-8', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            time.sleep(10)
            def tunnel_reader():
                nonlocal tunnelproc,tunneloutput,tunnelrawlog
                pattern = r'https://[\w\.-]+\.trycloudflare\.com'
                while True:
                    line = tunnelproc.stderr.readline() #cloudflare writes to stderr for some reason
                    tunnelrawlog += line+"\n"
                    if not line:
                        return
                    found = re.findall(pattern, line)
                    for x in found:
                        tunneloutput = x
                        print(f"Your remote Kobold API can be found at {tunneloutput}/api")
                        print(f"Your remote OpenAI Compatible API can be found at {tunneloutput}/v1")
                        if has_sd:
                            print(f"StableUI is available at {tunneloutput}/sdui/")
                        print("======\n")
                        print(f"Your remote tunnel is ready, please connect to {tunneloutput}", flush=True)
                        return

            tunnel_reader_thread = threading.Thread(target=tunnel_reader)
            tunnel_reader_thread.start()
            time.sleep(5)
            if tunneloutput=="":
                print(f"Error: Could not create cloudflare tunnel!\nMore Info:\n{tunnelrawlog}", flush=True)
            time.sleep(0.5)
            tunnelproc.wait()

        if os.name == 'nt':
            if os.path.exists("cloudflared.exe") and os.path.getsize("cloudflared.exe") > 1000000:
                print("Cloudflared file exists, reusing it...")
            else:
                print("Downloading Cloudflare Tunnel for Windows...")
                subprocess.run("curl -fL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe -o cloudflared.exe", shell=True, capture_output=True, text=True, check=True, encoding='utf-8')
        elif sys.platform=="darwin":
            if os.path.exists("cloudflared") and os.path.getsize("cloudflared") > 1000000:
                print("Cloudflared file exists, reusing it...")
            else:
                print("Downloading Cloudflare Tunnel for MacOS...")
                subprocess.run("curl -fL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-amd64.tgz -o cloudflared-darwin-amd64.tgz", shell=True, capture_output=True, text=True, check=True, encoding='utf-8')
                subprocess.run("tar -xzf cloudflared-darwin-amd64.tgz", shell=True)
                subprocess.run("chmod +x 'cloudflared'", shell=True)
        else:
            if os.path.exists("cloudflared-linux-amd64") and os.path.getsize("cloudflared-linux-amd64") > 1000000:
                print("Cloudflared file exists, reusing it...")
            else:
                print("Downloading Cloudflare Tunnel for Linux...")
                subprocess.run("curl -fL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o cloudflared-linux-amd64", shell=True, capture_output=True, text=True, check=True, encoding='utf-8')
                subprocess.run("chmod +x 'cloudflared-linux-amd64'", shell=True)
        print("Attempting to start tunnel thread...", flush=True)
        tunnel_thread = threading.Thread(target=run_tunnel)
        tunnel_thread.start()
    except Exception as ex:
        print("Remote Tunnel Failed!")
        print(str(ex))
        return None

def unload_libs():
    global handle
    OS = platform.system()
    dll_close = None
    if OS == "Windows":  # pragma: Windows
        from ctypes import wintypes
        dll_close = ctypes.windll.kernel32.FreeLibrary
        dll_close.argtypes = [wintypes.HMODULE]
        dll_close.restype = ctypes.c_int
    elif OS == "Darwin":
        try:
            try:  # macOS 11 (Big Sur). Possibly also later macOS 10s.
                stdlib = ctypes.CDLL("libc.dylib")
            except OSError:
                stdlib = ctypes.CDLL("libSystem")
        except OSError:
            # Older macOSs. Not only is the name inconsistent but it's
            # not even in PATH.
            stdlib = ctypes.CDLL("/usr/lib/system/libsystem_c.dylib")
        dll_close = stdlib.dlclose
        dll_close.argtypes = [ctypes.c_void_p]
        dll_close.restype = ctypes.c_int
    elif OS == "Linux":
        try:
            stdlib = ctypes.CDLL("")
        except OSError:
            stdlib = ctypes.CDLL("libc.so") # Alpine Linux.
        dll_close = stdlib.dlclose
        dll_close.argtypes = [ctypes.c_void_p]
        dll_close.restype = ctypes.c_int
    elif sys.platform == "msys":
        # msys can also use `ctypes.CDLL("kernel32.dll").FreeLibrary()`.
        stdlib = ctypes.CDLL("msys-2.0.dll")
        dll_close = stdlib.dlclose
        dll_close.argtypes = [ctypes.c_void_p]
        dll_close.restype = ctypes.c_int
    elif sys.platform == "cygwin":
        stdlib = ctypes.CDLL("cygwin1.dll")
        dll_close = stdlib.dlclose
        dll_close.argtypes = [ctypes.c_void_p]
        dll_close.restype = ctypes.c_int
    elif OS == "FreeBSD":
        # FreeBSD uses `/usr/lib/libc.so.7` where `7` is another version number.
        # It is not in PATH but using its name instead of its path is somehow the
        # only way to open it. The name must include the .so.7 suffix.
        stdlib = ctypes.CDLL("libc.so.7")
        dll_close = stdlib.close

    if handle and dll_close:
        print("Unloading Libraries...")
        dll_close(handle._handle)
        del handle.load_model
        del handle.generate
        del handle.new_token
        del handle.get_stream_count
        del handle.has_finished
        del handle.get_last_eval_time
        del handle.get_last_process_time
        del handle.get_last_token_count
        del handle.get_last_seed
        del handle.get_total_gens
        del handle.get_last_stop_reason
        del handle.abort_generate
        del handle.token_count
        del handle.get_pending_output
        del handle
        handle = None

def load_config_cli(filename):
    print("Loading .kcpps configuration file...")
    with open(filename, 'r') as f:
        config = json.load(f)
        args.istemplate = False
        raw_args = (sys.argv[1:]) #a lousy hack to allow for overriding kcpps
        for key, value in config.items():
            if f"--{key}" in raw_args:
                if key!="config":
                    print(f"Overriding Config Value: {key}")
            else:
                setattr(args, key, value)
        if args.istemplate:
            print("\nA .kcppt template was selected from CLI - automatically selecting your backend...")
            auto_set_backend_cli()


def delete_old_pyinstaller():
    try:
        base_path = sys._MEIPASS
    except Exception:
        return # not running from pyinstaller
    if not base_path:
        return

    import time, os, shutil
    selfdirpath = os.path.abspath(base_path)
    temp_parentdir_path = os.path.abspath(os.path.join(base_path, '..'))
    for dirname in os.listdir(temp_parentdir_path):
        absdirpath = os.path.abspath(os.path.join(temp_parentdir_path, dirname))
        if os.path.isdir(absdirpath) and os.path.basename(absdirpath).startswith('_MEI'): #only delete kobold pyinstallers
            if absdirpath!=selfdirpath and (time.time() - os.path.getctime(absdirpath)) > 14400: # remove if older than 4 hours
                kobold_itemcheck1 = os.path.join(absdirpath, 'koboldcpp_default.dll')
                kobold_itemcheck2 = os.path.join(absdirpath, 'koboldcpp_default.so')
                kobold_itemcheck3 = os.path.join(absdirpath, 'klite.embd')
                kobold_itemcheck4 = os.path.join(absdirpath, 'cublasLt64_11.dll')
                kobold_itemcheck5 = os.path.join(absdirpath, 'cublas64_11.dll')
                kobold_itemcheck6 = os.path.join(absdirpath, 'clblast.dll')
                if os.path.exists(kobold_itemcheck1) or os.path.exists(kobold_itemcheck2) or os.path.exists(kobold_itemcheck3) or (os.path.exists(kobold_itemcheck4) and os.path.exists(kobold_itemcheck5) and os.path.exists(kobold_itemcheck6)):
                    try:
                        shutil.rmtree(absdirpath)
                        print(f"Deleted orphaned pyinstaller dir: {absdirpath}")
                    except Exception as e:
                        print(f"Error deleting orphaned pyinstaller dir: {absdirpath}: {e}")

def sanitize_string(input_string):
    # alphanumeric characters, dots, dashes, and underscores
    import re
    sanitized_string = re.sub( r'[^\w\d\.\-_]', '', input_string)
    return sanitized_string

def download_model_from_url_internal(url): #returns path to downloaded model when done
    import subprocess
    mdlfilename = os.path.basename(url)
    #check if file already exists
    if mdlfilename:
        if os.path.exists(mdlfilename) and os.path.getsize(mdlfilename) > 10000000: #10MB trigger
            print(f"File {mdlfilename} already exists, not redownloading.")
            return mdlfilename
        else:
            dl_url = url
            if "https://huggingface.co/" in dl_url and "/blob/main/" in dl_url:
                dl_url = dl_url.replace("/blob/main/", "/resolve/main/")
            print(f"Downloading file from external URL at {dl_url} now...")
            subprocess.run(f"curl -fL {dl_url} -o {mdlfilename}", shell=True, capture_output=True, text=True, check=True, encoding='utf-8')
            print(f"Download {mdlfilename} completed.", flush=True)
            return mdlfilename
    return None
def download_model_from_url(url,permitted_types=[".gguf",".safetensors"]):
    if url and url!="":
        if url.endswith("?download=true"):
            url = url.replace("?download=true","")
        end_ext_ok = False
        for t in permitted_types:
            if url.endswith(t):
                end_ext_ok = True
                break
        if ((url.startswith("http://") or url.startswith("https://")) and end_ext_ok):
            dlfile = download_model_from_url_internal(url)
            return dlfile
    return None

def main(launch_args,start_server=True):
    global embedded_kailite, embedded_kcpp_docs, embedded_kcpp_sdui
    global libname, args, friendlymodelname, friendlysdmodelname, fullsdmodelpath, mmprojpath, password, fullwhispermodelpath

    args = launch_args
    if (args.model_param or args.model) and args.prompt and not args.benchmark and not (args.debugmode >= 1):
        suppress_stdout()

    print(f"***\nWelcome to KoboldCpp - Version {KcppVersion}") # just update version manually
    # print("Python version: " + sys.version)

    #perform some basic cleanup of old temporary directories
    try:
        delete_old_pyinstaller()
    except Exception as e:
        print(f"Error cleaning up orphaned pyinstaller dirs: {e}")

    if args.unpack:
        unpack_to_dir(args.unpack)
        return

    if args.config and len(args.config)==1:
        cfgname = args.config[0]
        if isinstance(cfgname, str):
            dlfile = download_model_from_url(cfgname,[".kcpps",".kcppt"])
            if dlfile:
                cfgname = dlfile
        if isinstance(cfgname, str) and os.path.exists(cfgname):
           load_config_cli(cfgname)
        elif args.ignoremissing:
            print("Ignoring missing kcpp config file...")
        else:
            global exitcounter
            exitcounter = 999
            exit_with_error(2,"Specified kcpp config file invalid or not found.")
    args = convert_outdated_args(args)

    #positional handling for kcpps files (drag and drop)
    if args.model_param and args.model_param!="" and (args.model_param.lower().endswith('.kcpps') or args.model_param.lower().endswith('.kcppt')):
        load_config_cli(args.model_param)

    #prevent quantkv from being used without flash attn
    if args.quantkv and args.quantkv>0 and not args.flashattention:
        exit_with_error(1, "Error: Using --quantkv requires --flashattention")

    if not args.model_param:
        args.model_param = args.model

    if args.showgui or (not args.model_param and not args.sdmodel and not args.whispermodel and not args.nomodel):
        #give them a chance to pick a file
        print("For command line arguments, please refer to --help")
        print("***")
        try:
            show_gui()
        except Exception as ex:
            exitcounter = 999
            ermsg = "Reason: " + str(ex) + "\nFile selection GUI unsupported.\ncustomtkinter python module required!\nPlease check command line: script.py --help"
            show_gui_msgbox("Warning, GUI failed to start",ermsg)
            if args.skiplauncher:
                print(f"Note: In order to use --skiplauncher, you need to specify a model with --model")
            time.sleep(3)
            sys.exit(2)

    #try to read story if provided
    if args.preloadstory:
        global preloaded_story
        canload = False
        if isinstance(args.preloadstory, str) and os.path.exists(args.preloadstory):
            print(f"Preloading saved story {args.preloadstory} into server...")
            with open(args.preloadstory, mode='rb') as f:
                preloaded_story = f.read()
                canload = True
        elif isinstance(args.preloadstory, str):
            print(f"Preloading saved story as JSON into server...")
            try:
                import ast
                parsed = ast.literal_eval(args.preloadstory)
                preloaded_story = json.dumps(parsed).encode()
                canload = True
            except Exception as ex:
                print(ex)
        elif isinstance(args.preloadstory, dict):
            try:
                preloaded_story = json.dumps(args.preloadstory).encode()
                canload = True
            except Exception as ex:
                print(ex)
        if canload:
            print("Saved story preloaded.")
        else:
            print(f"Warning: Saved story file invalid or not found. No story will be preloaded into server.")

    # try to read chat completions adapter
    if args.chatcompletionsadapter:
        global chatcompl_adapter
        ccadapter_path = None
        canload = False
        adapt_dir = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'kcpp_adapters')
        adapt_dir = adapt_dir if os.path.isdir(adapt_dir) else None
        if isinstance(args.chatcompletionsadapter, str) and os.path.exists(args.chatcompletionsadapter):
            ccadapter_path = os.path.abspath(args.chatcompletionsadapter)
        elif isinstance(args.chatcompletionsadapter, str) and adapt_dir:
            filename = args.chatcompletionsadapter
            if not filename.endswith(".json"):
                filename += ".json"
            premade_adapt_path = os.path.join(adapt_dir,filename)
            if premade_adapt_path and os.path.exists(premade_adapt_path):
                ccadapter_path = os.path.abspath(premade_adapt_path)
        if ccadapter_path:
            print(f"Loading Chat Completions Adapter: {ccadapter_path}")
            with open(ccadapter_path, 'r') as f:
                chatcompl_adapter = json.load(f)
                canload = True
        else:
            if isinstance(args.chatcompletionsadapter, str) and args.chatcompletionsadapter!="":
                try:
                    import ast
                    parsed = ast.literal_eval(args.chatcompletionsadapter)
                    chatcompl_adapter = json.loads(json.dumps(parsed))
                    canload = True
                except Exception as ex:
                    print(ex)
            elif isinstance(args.chatcompletionsadapter, dict):
                try:
                    chatcompl_adapter = json.loads(json.dumps(args.chatcompletionsadapter))
                    canload = True
                except Exception as ex:
                    print(ex)
        if canload:
            print(f"Chat Completions Adapter Loaded")
        else:
            print(f"Warning: Chat Completions Adapter invalid or not found.")

    # handle model downloads if needed
    if args.model_param and args.model_param!="":
        dlfile = download_model_from_url(args.model_param,[".gguf",".bin"])
        if dlfile:
            args.model_param = dlfile
    if args.sdmodel and args.sdmodel!="":
        dlfile = download_model_from_url(args.sdmodel,[".gguf",".safetensors"])
        if dlfile:
            args.sdmodel = dlfile
    if args.sdt5xxl and args.sdt5xxl!="":
        dlfile = download_model_from_url(args.sdt5xxl,[".gguf",".safetensors"])
        if dlfile:
            args.sdt5xxl = dlfile
    if args.sdclipl and args.sdclipl!="":
        dlfile = download_model_from_url(args.sdclipl,[".gguf",".safetensors"])
        if dlfile:
            args.sdclipl = dlfile
    if args.sdclipg and args.sdclipg!="":
        dlfile = download_model_from_url(args.sdclipg,[".gguf",".safetensors"])
        if dlfile:
            args.sdclipg = dlfile
    if args.sdvae and args.sdvae!="":
        dlfile = download_model_from_url(args.sdvae,[".gguf",".safetensors"])
        if dlfile:
            args.sdvae = dlfile
    if args.mmproj and args.mmproj!="":
        dlfile = download_model_from_url(args.mmproj,[".gguf"])
        if dlfile:
            args.mmproj = dlfile
    if args.whispermodel and args.whispermodel!="":
        dlfile = download_model_from_url(args.whispermodel,[".gguf",".bin"])
        if dlfile:
            args.whispermodel = dlfile
    if args.draftmodel and args.draftmodel!="":
        dlfile = download_model_from_url(args.draftmodel,[".gguf"])
        if dlfile:
            args.draftmodel = dlfile

    # sanitize and replace the default vanity name. remember me....
    if args.model_param and args.model_param!="":
        newmdldisplayname = os.path.basename(args.model_param)
        newmdldisplayname = os.path.splitext(newmdldisplayname)[0]
        friendlymodelname = "koboldcpp/" + sanitize_string(newmdldisplayname)

    # horde worker settings
    global maxhordelen, maxhordectx, showdebug, has_multiplayer
    if args.hordemodelname and args.hordemodelname!="":
        friendlymodelname = args.hordemodelname
        if args.debugmode == 1:
            friendlymodelname = "debug-" + friendlymodelname
        if not friendlymodelname.startswith("koboldcpp/"):
            friendlymodelname = "koboldcpp/" + friendlymodelname
    if (args.hordemodelname and args.hordemodelname!="") or (args.hordeworkername and args.hordeworkername!="") or (args.hordekey and args.hordekey!=""):
        if args.debugmode == 0:
            args.debugmode = -1
    if args.hordegenlen and args.hordegenlen > 0:
        maxhordelen = int(args.hordegenlen)
    if args.hordemaxctx and args.hordemaxctx > 0:
        maxhordectx = int(args.hordemaxctx)

    if args.debugmode != 1:
        showdebug = False

    if args.multiplayer:
        has_multiplayer = True

    if args.highpriority:
        print("Setting process to Higher Priority - Use Caution")
        try:
            import psutil
            os_used = sys.platform
            process = psutil.Process(os.getpid())  # Set high priority for the python script for the CPU
            oldprio = process.nice()
            if os_used == "win32":  # Windows (either 32-bit or 64-bit)
                process.nice(psutil.REALTIME_PRIORITY_CLASS)
                print("High Priority for Windows Set: " + str(oldprio) + " to " + str(process.nice()))
            elif os_used == "linux":  # linux
                process.nice(psutil.IOPRIO_CLASS_RT)
                print("High Priority for Linux Set: " + str(oldprio) + " to " + str(process.nice()))
            else:  # MAC OS X or other
                process.nice(-18)
                print("High Priority for Other OS Set :" + str(oldprio) + " to " + str(process.nice()))
        except Exception as ex:
             print("Error, Could not change process priority: " + str(ex))

    if args.contextsize:
        global maxctx
        maxctx = args.contextsize

    if args.nocertify:
        global nocertify
        nocertify = True

    if args.gpulayers:
        shouldavoidgpu = False
        if args.usecpu and sys.platform!="darwin":
            shouldavoidgpu = True
            if args.gpulayers and args.gpulayers>0:
                print("WARNING: GPU layers is set, but a GPU backend was not selected! GPU will not be used!")
            args.gpulayers = 0
        elif args.gpulayers==-1 and sys.platform=="darwin" and args.model_param and os.path.exists(args.model_param):
            print(f"MacOS detected: Auto GPU layers set to maximum")
            args.gpulayers = 200
        elif not shouldavoidgpu and args.model_param and os.path.exists(args.model_param):
            if (args.usecublas is None) and (args.usevulkan is None) and (args.useclblast is None):
                print("No GPU or CPU backend was selected. Trying to assign one for you automatically...")
                auto_set_backend_cli()
            if MaxMemory[0] == 0: #try to get gpu vram for cuda if not picked yet
                fetch_gpu_properties(False,True,True)
                pass
            if args.gpulayers==-1:
                if MaxMemory[0] > 0 and (not args.usecpu) and ((args.usecublas is not None) or (args.usevulkan is not None) or (args.useclblast is not None) or sys.platform=="darwin"):
                    extract_modelfile_params(args.model_param,args.sdmodel,args.whispermodel,args.mmproj,args.draftmodel)
                    layeramt = autoset_gpu_layers(args.contextsize,args.sdquant,args.blasbatchsize)
                    print(f"Auto Recommended GPU Layers: {layeramt}")
                    args.gpulayers = layeramt
                else:
                    print(f"No GPU backend found, or could not automatically determine GPU layers. Please set it manually.")
                    args.gpulayers = 0

    if args.threads == -1:
        args.threads = get_default_threads()
        print(f"Auto Set Threads: {args.threads}")

    init_library() # Note: if blas does not exist and is enabled, program will crash.
    print("==========")
    time.sleep(1)

    #handle loading text model
    if args.model_param:
        if not os.path.exists(args.model_param):
            if args.ignoremissing:
                print(f"Ignoring missing model file: {args.model_param}")
                args.model_param = None
            else:
                exitcounter = 999
                exit_with_error(2,f"Cannot find text model file: {args.model_param}")

        if args.lora and args.lora[0]!="":
            if not os.path.exists(args.lora[0]):
                if args.ignoremissing:
                    print(f"Ignoring missing lora file: {args.lora[0]}")
                    args.lora = None
                else:
                    exitcounter = 999
                    exit_with_error(2,f"Cannot find lora file: {args.lora[0]}")
            else:
                args.lora[0] = os.path.abspath(args.lora[0])
                if len(args.lora) > 1:
                    if not os.path.exists(args.lora[1]):
                        if args.ignoremissing:
                            print(f"Ignoring missing lora base: {args.lora[1]}")
                            args.lora = None
                        else:
                            exitcounter = 999
                            exit_with_error(2,f"Cannot find lora base: {args.lora[1]}")

                    else:
                        args.lora[1] = os.path.abspath(args.lora[1])

        if args.mmproj and args.mmproj!="":
            if not os.path.exists(args.mmproj):
                if args.ignoremissing:
                    print(f"Ignoring missing mmproj file: {args.mmproj}")
                    args.mmproj = None
                else:
                    exitcounter = 999
                    exit_with_error(2,f"Cannot find mmproj file: {args.mmproj}")
            else:
                global mmprojpath
                args.mmproj = os.path.abspath(args.mmproj)
                mmprojpath = args.mmproj

        if args.password and args.password!="":
            password = args.password.strip()

        if not args.blasthreads or args.blasthreads <= 0:
            args.blasthreads = args.threads

        modelname = os.path.abspath(args.model_param)
        print(args)
        # Flush stdout for win32 issue with regards to piping in terminals,
        # especially before handing over to C++ context.
        print(f"==========\nLoading model: {modelname}", flush=True)
        loadok = load_model(modelname)
        print("Load Text Model OK: " + str(loadok))

        if not loadok:
            exitcounter = 999
            exit_with_error(3,"Could not load text model: " + modelname)

    #handle loading image model
    if args.sdmodel and args.sdmodel!="":
        imgmodel = args.sdmodel
        if not imgmodel or not os.path.exists(imgmodel):
            if args.ignoremissing:
                print(f"Ignoring missing img model file: {imgmodel}")
                args.sdmodel = None
            else:
                exitcounter = 999
                exit_with_error(2,f"Cannot find image model file: {imgmodel}")
        else:
            imglora = ""
            imgvae = ""
            imgt5xxl = ""
            imgclipl = ""
            imgclipg = ""
            if args.sdlora:
                if os.path.exists(args.sdlora):
                    imglora = os.path.abspath(args.sdlora)
                else:
                    print(f"Missing SD LORA model file...")
            if args.sdvae:
                if os.path.exists(args.sdvae):
                    imgvae = os.path.abspath(args.sdvae)
                else:
                    print(f"Missing SD VAE model file...")
            if args.sdt5xxl:
                if os.path.exists(args.sdt5xxl):
                    imgt5xxl = os.path.abspath(args.sdt5xxl)
                else:
                    print(f"Missing SD T5-XXL model file...")
            if args.sdclipl:
                if os.path.exists(args.sdclipl):
                    imgclipl = os.path.abspath(args.sdclipl)
                else:
                    print(f"Missing SD Clip-L model file...")
            if args.sdclipg:
                if os.path.exists(args.sdclipg):
                    imgclipg = os.path.abspath(args.sdclipg)
                else:
                    print(f"Missing SD Clip-G model file...")

            imgmodel = os.path.abspath(imgmodel)
            fullsdmodelpath = imgmodel
            friendlysdmodelname = os.path.basename(imgmodel)
            friendlysdmodelname = os.path.splitext(friendlysdmodelname)[0]
            friendlysdmodelname = sanitize_string(friendlysdmodelname)
            loadok = sd_load_model(imgmodel,imgvae,imglora,imgt5xxl,imgclipl,imgclipg)
            print("Load Image Model OK: " + str(loadok))
            if not loadok:
                exitcounter = 999
                exit_with_error(3,"Could not load image model: " + imgmodel)

    #handle whisper model
    if args.whispermodel and args.whispermodel!="":
        whispermodel = args.whispermodel
        if not whispermodel or not os.path.exists(whispermodel):
            if args.ignoremissing:
                print(f"Ignoring missing whisper model file: {whispermodel}")
                args.whispermodel = None
            else:
                exitcounter = 999
                exit_with_error(2,f"Cannot find whisper model file: {whispermodel}")
        else:
            whispermodel = os.path.abspath(whispermodel)
            fullwhispermodelpath = whispermodel
            loadok = whisper_load_model(whispermodel)
            print("Load Whisper Model OK: " + str(loadok))
            if not loadok:
                exitcounter = 999
                exit_with_error(3,"Could not load whisper model: " + whispermodel)


    #load embedded lite
    try:
        basepath = os.path.abspath(os.path.dirname(os.path.realpath(__file__)))
        with open(os.path.join(basepath, "klite.embd"), mode='rb') as f:
            embedded_kailite = f.read()
            # patch it with extra stuff
            origStr = "Sorry, KoboldAI Lite requires Javascript to function."
            patchedStr = "Sorry, KoboldAI Lite requires Javascript to function.<br>You can use <a class=\"color_blueurl\" href=\"/noscript\">KoboldCpp NoScript mode</a> instead."
            embedded_kailite = embedded_kailite.decode("UTF-8","ignore")
            embedded_kailite = embedded_kailite.replace(origStr, patchedStr)
            embedded_kailite = embedded_kailite.encode()
            print("Embedded KoboldAI Lite loaded.")
    except Exception as e:
        print("Could not find KoboldAI Lite. Embedded KoboldAI Lite will not be available.")

    try:
        basepath = os.path.abspath(os.path.dirname(os.path.realpath(__file__)))
        with open(os.path.join(basepath, "kcpp_docs.embd"), mode='rb') as f:
            embedded_kcpp_docs = f.read()
            print("Embedded API docs loaded.")
    except Exception as e:
        print("Could not find Embedded KoboldCpp API docs.")

    try:
        basepath = os.path.abspath(os.path.dirname(os.path.realpath(__file__)))
        with open(os.path.join(basepath, "kcpp_sdui.embd"), mode='rb') as f:
            embedded_kcpp_sdui = f.read()
            if args.sdmodel:
                print("Embedded SDUI loaded.")
    except Exception as e:
        print("Could not find Embedded SDUI.")

    if args.port_param!=defaultport:
        args.port = args.port_param

    global sslvalid
    if args.ssl:
        if len(args.ssl)==2 and isinstance(args.ssl[0], str) and os.path.exists(args.ssl[0]) and isinstance(args.ssl[1], str) and os.path.exists(args.ssl[1]):
            sslvalid = True
            print("SSL configuration is valid and will be used.")
        else:
            print("Your SSL configuration is INVALID. SSL will not be used.")
    epurl = ""
    httpsaffix = ("https" if sslvalid else "http")
    if args.host=="":
        epurl = f"{httpsaffix}://localhost:{args.port}"
    else:
        epurl = f"{httpsaffix}://{args.host}:{args.port}"
    if not args.remotetunnel:
        print(f"Starting Kobold API on port {args.port} at {epurl}/api/")
        print(f"Starting OpenAI Compatible API on port {args.port} at {epurl}/v1/")
        if args.sdmodel:
            print(f"StableUI is available at {epurl}/sdui/")

    if args.launch:
        try:
            import webbrowser as wb
            wb.open(epurl)
        except:
            print("--launch was set, but could not launch web browser automatically.")

    if args.hordekey and args.hordekey!="":
        if args.hordeworkername and args.hordeworkername!="":
            horde_thread = threading.Thread(target=run_horde_worker,args=(args,args.hordekey,args.hordeworkername))
            horde_thread.daemon = True
            horde_thread.start()
        else:
            print("Horde worker could not start. You need to specify a horde worker name with --hordeworkername")

    #if post-ready script specified, execute it
    if args.onready:
        def onready_subprocess():
            import subprocess
            print("Starting Post-Load subprocess...")
            subprocess.run(args.onready[0], shell=True)
        timer_thread = threading.Timer(1, onready_subprocess) #1 second delay
        timer_thread.start()

    if args.model_param and (args.benchmark or args.prompt):
        start_server = False
        save_to_file = (args.benchmark and args.benchmark!="stdout" and args.benchmark!="")
        benchmaxctx = maxctx
        benchlen = args.promptlimit
        benchtemp = 0.1
        benchtopk = 1
        benchreppen = 1
        benchbaneos = True
        benchmodel = sanitize_string(os.path.splitext(os.path.basename(modelname))[0])
        benchprompt = ""
        if args.prompt:
            benchprompt = args.prompt
            benchtopk = 100
            benchreppen = 1.07
            benchtemp = 0.8
            if not args.benchmark:
                benchbaneos = False
        if args.benchmark:
            if os.path.exists(args.benchmark) and os.path.getsize(args.benchmark) > 1000000:
                print(f"\nWarning: The benchmark CSV output file you selected exceeds 1MB. This is probably not what you want, did you select the wrong CSV file?\nFor safety, benchmark output will not be saved.")
                save_to_file = False
            if save_to_file:
                print(f"\nRunning benchmark (Save to File: {args.benchmark})...")
            else:
                print(f"\nRunning benchmark (Not Saved)...")
            if benchprompt=="":
                benchprompt = " 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1"
                for i in range(0,14): #generate massive prompt
                    benchprompt += benchprompt
        genp = {
            "prompt":benchprompt,
            "max_length":benchlen,
            "max_context_length":benchmaxctx,
            "temperature":benchtemp,
            "top_k":benchtopk,
            "rep_pen":benchreppen,
            "ban_eos_token":benchbaneos
        }
        genout = generate(genparams=genp)
        result = genout['text']
        if args.prompt and not args.benchmark:
            restore_stdout()
            print(result)
        if args.benchmark:
            result = (result[:8] if len(result)>8 else "") if not args.prompt else result
            t_pp = float(handle.get_last_process_time())*float(benchmaxctx-benchlen)*0.001
            t_gen = float(handle.get_last_eval_time())*float(benchlen)*0.001
            s_pp = float(benchmaxctx-benchlen)/t_pp
            s_gen = float(benchlen)/t_gen
            datetimestamp = datetime.now(timezone.utc)
            benchflagstr = f"NoAVX2={args.noavx2} Threads={args.threads} HighPriority={args.highpriority} Cublas_Args={args.usecublas} Tensor_Split={args.tensor_split} BlasThreads={args.blasthreads} BlasBatchSize={args.blasbatchsize} FlashAttention={args.flashattention} KvCache={args.quantkv}"
            print(f"\nBenchmark Completed - v{KcppVersion} Results:\n======")
            print(f"Flags: {benchflagstr}")
            print(f"Timestamp: {datetimestamp}")
            print(f"Backend: {libname}")
            print(f"Layers: {args.gpulayers}")
            print(f"Model: {benchmodel}")
            print(f"MaxCtx: {benchmaxctx}")
            print(f"GenAmount: {benchlen}\n-----")
            print(f"ProcessingTime: {t_pp:.3f}s")
            print(f"ProcessingSpeed: {s_pp:.2f}T/s")
            print(f"GenerationTime: {t_gen:.3f}s")
            print(f"GenerationSpeed: {s_gen:.2f}T/s")
            print(f"TotalTime: {(t_pp+t_gen):.3f}s")
            print(f"Output: {result}\n-----")
            if save_to_file:
                try:
                    with open(args.benchmark, "a") as file:
                        file.seek(0, 2)
                        if file.tell() == 0: #empty file
                            file.write(f"Timestamp,Backend,Layers,Model,MaxCtx,GenAmount,ProcessingTime,ProcessingSpeed,GenerationTime,GenerationSpeed,TotalTime,Output,Flags")
                        file.write(f"\n{datetimestamp},{libname},{args.gpulayers},{benchmodel},{benchmaxctx},{benchlen},{t_pp:.2f},{s_pp:.2f},{t_gen:.2f},{s_gen:.2f},{(t_pp+t_gen):.2f},{result},{benchflagstr}")
                except Exception as e:
                    print(f"Error writing benchmark to file: {e}")
            global using_gui_launcher
            if using_gui_launcher and not save_to_file:
                print("===")
                print("Press ENTER key to exit.", flush=True)
                input()

    check_deprecation_warning()
    if start_server:
        if args.remotetunnel:
            setuptunnel(True if args.sdmodel else False)
        else:
            # Flush stdout for previous win32 issue so the client can see output.
            print(f"======\nPlease connect to custom endpoint at {epurl}", flush=True)
        asyncio.run(RunServerMultiThreaded(args.host, args.port))
    else:
        # Flush stdout for previous win32 issue so the client can see output.
        if not args.prompt or args.benchmark:
            print(f"Server was not started, main function complete. Idling.", flush=True)

def run_in_queue(launch_args, input_queue, output_queue):
    main(launch_args, start_server=False)
    output_queue.put({'command': 'complete'})
    while True:
        if not input_queue.empty():
            while not input_queue.empty():
                data = input_queue.get()
                if data['command'] == 'generate':
                    pl = data['data']
                    genout = generate(genparams=pl)
                    result = genout['text']
                    output_queue.put({'command': 'generated text', 'data': result})
        time.sleep(0.2)

def start_in_seperate_process(launch_args):
    import multiprocessing
    input_queue = multiprocessing.Queue()
    output_queue = multiprocessing.Queue()
    p = multiprocessing.Process(target=run_in_queue, args=(launch_args, input_queue, output_queue))
    p.start()
    return (output_queue, input_queue, p)

if __name__ == '__main__':

    def check_range(value_type, min_value, max_value):
        def range_checker(arg: str):
            try:
                f = value_type(arg)
            except ValueError:
                raise argparse.ArgumentTypeError(f'must be a valid {value_type}')
            if f < min_value or f > max_value:
                raise argparse.ArgumentTypeError(f'must be within [{min_value}, {max_value}]')
            return f
        return range_checker

    parser = argparse.ArgumentParser(description=f'KoboldCpp Server - Version {KcppVersion}')
    modelgroup = parser.add_mutually_exclusive_group() #we want to be backwards compatible with the unnamed positional args
    modelgroup.add_argument("--model", metavar=('[filename]'), help="Model file to load", type=str, default="")
    modelgroup.add_argument("model_param", help="Model file to load (positional)", nargs="?")
    portgroup = parser.add_mutually_exclusive_group() #we want to be backwards compatible with the unnamed positional args
    portgroup.add_argument("--port", metavar=('[portnumber]'), help="Port to listen on", default=defaultport, type=int, action='store')
    portgroup.add_argument("port_param", help="Port to listen on (positional)", default=defaultport, nargs="?", type=int, action='store')
    parser.add_argument("--host", metavar=('[ipaddr]'), help="Host IP to listen on. If this flag is not set, all routable interfaces are accepted.", default="")
    parser.add_argument("--launch", help="Launches a web browser when load is completed.", action='store_true')
    parser.add_argument("--config", metavar=('[filename]'), help="Load settings from a .kcpps file. Other arguments will be ignored", type=str, nargs=1)

    parser.add_argument("--threads", metavar=('[threads]'), help="Use a custom number of threads if specified. Otherwise, uses an amount based on CPU cores", type=int, default=get_default_threads())
    compatgroup = parser.add_mutually_exclusive_group()
    compatgroup.add_argument("--usecublas", help="Use CuBLAS for GPU Acceleration. Requires CUDA. Select lowvram to not allocate VRAM scratch buffer. Enter a number afterwards to select and use 1 GPU. Leaving no number will use all GPUs. For hipBLAS binaries, please check YellowRoseCx rocm fork.", nargs='*',metavar=('[lowvram|normal] [main GPU ID] [mmq] [rowsplit]'), choices=['normal', 'lowvram', '0', '1', '2', '3', 'mmq', 'rowsplit'])
    compatgroup.add_argument("--usevulkan", help="Use Vulkan for GPU Acceleration. Can optionally specify GPU Device ID (e.g. --usevulkan 0).", metavar=('[Device ID]'), nargs='*', type=int, default=None)
    compatgroup.add_argument("--useclblast", help="Use CLBlast for GPU Acceleration. Must specify exactly 2 arguments, platform ID and device ID (e.g. --useclblast 1 0).", type=int, choices=range(0,9), nargs=2)
    compatgroup.add_argument("--usecpu", help="Do not use any GPU acceleration (CPU Only)", action='store_true')
    parser.add_argument("--contextsize", help="Controls the memory allocated for maximum context size, only change if you need more RAM for big contexts. (default 4096). Supported values are [256,512,1024,2048,3072,4096,6144,8192,12288,16384,24576,32768,49152,65536,98304,131072]. IF YOU USE ANYTHING ELSE YOU ARE ON YOUR OWN.",metavar=('[256,512,1024,2048,3072,4096,6144,8192,12288,16384,24576,32768,49152,65536,98304,131072]'), type=check_range(int,256,262144), default=4096)
    parser.add_argument("--gpulayers", help="Set number of layers to offload to GPU when using GPU. Requires GPU. Set to -1 to try autodetect, set to 0 to disable GPU offload.",metavar=('[GPU layers]'), nargs='?', const=1, type=int, default=-1)
    parser.add_argument("--tensor_split", help="For CUDA and Vulkan only, ratio to split tensors across multiple GPUs, space-separated list of proportions, e.g. 7 3", metavar=('[Ratios]'), type=float, nargs='+')

    #more advanced params
    advparser = parser.add_argument_group('Advanced Commands')
    advparser.add_argument("--ropeconfig", help="If set, uses customized RoPE scaling from configured frequency scale and frequency base (e.g. --ropeconfig 0.25 10000). Otherwise, uses NTK-Aware scaling set automatically based on context size. For linear rope, simply set the freq-scale and ignore the freq-base",metavar=('[rope-freq-scale]', '[rope-freq-base]'), default=[0.0, 10000.0], type=float, nargs='+')
    advparser.add_argument("--blasbatchsize", help="Sets the batch size used in BLAS processing (default 512). Setting it to -1 disables BLAS mode, but keeps other benefits like GPU offload.", type=int,choices=[-1,32,64,128,256,512,1024,2048], default=512)
    advparser.add_argument("--blasthreads", help="Use a different number of threads during BLAS if specified. Otherwise, has the same value as --threads",metavar=('[threads]'), type=int, default=0)
    advparser.add_argument("--lora", help="LLAMA models only, applies a lora file on top of model. Experimental.", metavar=('[lora_filename]', '[lora_base]'), nargs='+')
    advparser.add_argument("--noshift", help="If set, do not attempt to Trim and Shift the GGUF context.", action='store_true')
    advparser.add_argument("--nofastforward", help="If set, do not attempt to fast forward GGUF context (always reprocess). Will also enable noshift", action='store_true')
    advparser.add_argument("--nommap", help="If set, do not use mmap to load newer models", action='store_true')
    advparser.add_argument("--usemlock", help="Enables mlock, preventing the RAM used to load the model from being paged out. Not usually recommended.", action='store_true')
    advparser.add_argument("--noavx2", help="Do not use AVX2 instructions, a slower compatibility mode for older devices.", action='store_true')
    advparser.add_argument("--debugmode", help="Shows additional debug info in the terminal.", nargs='?', const=1, type=int, default=0)
    advparser.add_argument("--onready", help="An optional shell command to execute after the model has been loaded.", metavar=('[shell command]'), type=str, default="",nargs=1)
    advparser.add_argument("--benchmark", help="Do not start server, instead run benchmarks. If filename is provided, appends results to provided file.", metavar=('[filename]'), nargs='?', const="stdout", type=str, default=None)
    advparser.add_argument("--prompt", metavar=('[prompt]'), help="Passing a prompt string triggers a direct inference, loading the model, outputs the response to stdout and exits. Can be used alone or with benchmark.", type=str, default="")
    advparser.add_argument("--promptlimit", help="Sets the maximum number of generated tokens, usable only with --prompt or --benchmark",metavar=('[token limit]'), type=int, default=100)
    advparser.add_argument("--multiuser", help="Runs in multiuser mode, which queues incoming requests instead of blocking them.", metavar=('limit'), nargs='?', const=1, type=int, default=1)
    advparser.add_argument("--multiplayer", help="Hosts a shared multiplayer session that others can join.", action='store_true')
    advparser.add_argument("--remotetunnel", help="Uses Cloudflare to create a remote tunnel, allowing you to access koboldcpp remotely over the internet even behind a firewall.", action='store_true')
    advparser.add_argument("--highpriority", help="Experimental flag. If set, increases the process CPU priority, potentially speeding up generation. Use caution.", action='store_true')
    advparser.add_argument("--foreground", help="Windows only. Sends the terminal to the foreground every time a new prompt is generated. This helps avoid some idle slowdown issues.", action='store_true')
    advparser.add_argument("--preloadstory", help="Configures a prepared story json save file to be hosted on the server, which frontends (such as KoboldAI Lite) can access over the API.", default="")
    advparser.add_argument("--quiet", help="Enable quiet mode, which hides generation inputs and outputs in the terminal. Quiet mode is automatically enabled when running a horde worker.", action='store_true')
    advparser.add_argument("--ssl", help="Allows all content to be served over SSL instead. A valid UNENCRYPTED SSL cert and key .pem files must be provided", metavar=('[cert_pem]', '[key_pem]'), nargs='+')
    advparser.add_argument("--nocertify", help="Allows insecure SSL connections. Use this if you have cert errors and need to bypass certificate restrictions.", action='store_true')
    advparser.add_argument("--mmproj", help="Select a multimodal projector file for vision models like LLaVA.", default="")
    advparser.add_argument("--draftmodel", help="Load a small draft model for speculative decoding. It will be fully offloaded. Vocab must match the main model.", default="")
    advparser.add_argument("--draftamount", metavar=('[tokens]'), help="How many tokens to draft per chunk before verifying results", type=int, default=default_draft_amount)
    advparser.add_argument("--password", help="Enter a password required to use this instance. This key will be required for all text endpoints. Image endpoints are not secured.", default=None)
    advparser.add_argument("--ignoremissing", help="Ignores all missing non-essential files, just skipping them instead.", action='store_true')
    advparser.add_argument("--chatcompletionsadapter", help="Select an optional ChatCompletions Adapter JSON file to force custom instruct tags.", default="")
    advparser.add_argument("--flashattention", help="Enables flash attention.", action='store_true')
    advparser.add_argument("--quantkv", help="Sets the KV cache data type quantization, 0=f16, 1=q8, 2=q4. Requires Flash Attention, and disables context shifting.",metavar=('[quantization level 0/1/2]'), type=int, choices=[0,1,2], default=0)
    advparser.add_argument("--forceversion", help="If the model file format detection fails (e.g. rogue modified model) you can set this to override the detected format (enter desired version, e.g. 401 for GPTNeoX-Type2).",metavar=('[version]'), type=int, default=0)
    advparser.add_argument("--smartcontext", help="Reserving a portion of context to try processing less frequently. Outdated. Not recommended.", action='store_true')
    advparser.add_argument("--unpack", help="Extracts the file contents of the KoboldCpp binary into a target directory.", metavar=('destination'), type=str, default="")
    advparser.add_argument("--nomodel", help="Allows you to launch the GUI alone, without selecting any model.", action='store_true')
    compatgroup2 = parser.add_mutually_exclusive_group()
    compatgroup2.add_argument("--showgui", help="Always show the GUI instead of launching the model right away when loading settings from a .kcpps file.", action='store_true')
    compatgroup2.add_argument("--skiplauncher", help="Doesn't display or use the GUI launcher.", action='store_true')

    hordeparsergroup = parser.add_argument_group('Horde Worker Commands')
    hordeparsergroup.add_argument("--hordemodelname", metavar=('[name]'), help="Sets your AI Horde display model name.", default="")
    hordeparsergroup.add_argument("--hordeworkername", metavar=('[name]'), help="Sets your AI Horde worker name.", default="")
    hordeparsergroup.add_argument("--hordekey", metavar=('[apikey]'), help="Sets your AI Horde API key.", default="")
    hordeparsergroup.add_argument("--hordemaxctx", metavar=('[amount]'), help="Sets the maximum context length your worker will accept from an AI Horde job.", type=int, default=0)
    hordeparsergroup.add_argument("--hordegenlen", metavar=('[amount]'), help="Sets the maximum number of tokens your worker will generate from an AI horde job.", type=int, default=0)

    sdparsergroup = parser.add_argument_group('Image Generation Commands')
    sdparsergroup.add_argument("--sdmodel", metavar=('[filename]'), help="Specify a stable diffusion safetensors or gguf model to enable image generation.", default="")
    sdparsergroup.add_argument("--sdthreads", metavar=('[threads]'), help="Use a different number of threads for image generation if specified. Otherwise, has the same value as --threads.", type=int, default=0)
    sdparsergroup.add_argument("--sdclamped", help="If specified, limit generation steps and resolution settings for shared use. Accepts an extra optional parameter that indicates maximum resolution (eg. 768 clamps to 768x768, min 512px, disabled if 0).", nargs='?', const=512, type=int, default=0)
    sdparsergroup.add_argument("--sdt5xxl", metavar=('[filename]'), help="Specify a T5-XXL safetensors model for use in SD3 or Flux. Leave blank if prebaked or unused.", default="")
    sdparsergroup.add_argument("--sdclipl", metavar=('[filename]'), help="Specify a Clip-L safetensors model for use in SD3 or Flux. Leave blank if prebaked or unused.", default="")
    sdparsergroup.add_argument("--sdclipg", metavar=('[filename]'), help="Specify a Clip-G safetensors model for use in SD3. Leave blank if prebaked or unused.", default="")
    sdparsergroupvae = sdparsergroup.add_mutually_exclusive_group()
    sdparsergroupvae.add_argument("--sdvae", metavar=('[filename]'), help="Specify a stable diffusion safetensors VAE which replaces the one in the model.", default="")
    sdparsergroupvae.add_argument("--sdvaeauto", help="Uses a built-in VAE via TAE SD, which is very fast, and fixed bad VAEs.", action='store_true')
    sdparsergrouplora = sdparsergroup.add_mutually_exclusive_group()
    sdparsergrouplora.add_argument("--sdquant", help="If specified, loads the model quantized to save memory.", action='store_true')
    sdparsergrouplora.add_argument("--sdlora", metavar=('[filename]'), help="Specify a stable diffusion LORA safetensors model to be applied. Cannot be used with quant models.", default="")
    sdparsergroup.add_argument("--sdloramult", metavar=('[amount]'), help="Multiplier for the LORA model to be applied.", type=float, default=1.0)

    whisperparsergroup = parser.add_argument_group('Whisper Transcription Commands')
    whisperparsergroup.add_argument("--whispermodel", metavar=('[filename]'), help="Specify a Whisper bin model to enable Speech-To-Text transcription.", default="")

    deprecatedgroup = parser.add_argument_group('Deprecated Commands, DO NOT USE!')
    deprecatedgroup.add_argument("--hordeconfig", help=argparse.SUPPRESS, nargs='+')
    deprecatedgroup.add_argument("--sdconfig", help=argparse.SUPPRESS, nargs='+')
    compatgroup.add_argument("--noblas", help=argparse.SUPPRESS, action='store_true')

    main(parser.parse_args(),start_server=True)
