#!/usr/bin/env python3

#importing the necessary modules 
import argparse
import sys
sys.path.append('../')
import os
import shutil

#deepstream and Gstreamer plugins
import pyds
import gi
import configparser
gi.require_version('Gst', '1.0')
from gi.repository import GObject, Gst
from gi.repository import GLib

#other utilites
import math
from common.is_aarch_64 import is_aarch64
from common.bus_call import bus_call





# create a directory to hold the segment and manifest files
hls_path = "./Hls_output"
if os.path.exists(hls_path) is False:
    os.mkdir(hls_path)
 
# create a sub-directory to hold the segment and manifest files
video_info = hls_path + '/' + "stream_data"
if not os.path.exists(video_info):
    os.makedirs(video_info, exist_ok=True)


MAX_DISPLAY_LEN=64
MUXER_OUTPUT_WIDTH=1920
MUXER_OUTPUT_HEIGHT=1080
MUXER_BATCH_TIMEOUT_USEC=4000000
TILED_OUTPUT_WIDTH=1280
TILED_OUTPUT_HEIGHT=720
GST_CAPS_FEATURES_NVMM="memory:NVMM"
OSD_PROCESS_MODE= 0
OSD_DISPLAY_TEXT= 1

PGIE_CLASS_ID_VEHICLE = 0
PGIE_CLASS_ID_BICYCLE = 1
PGIE_CLASS_ID_PERSON = 2
PGIE_CLASS_ID_ROADSIGN = 3

def pgie_src_pad_buffer_probe(pad,info,u_data):


    
    #Intiallizing object counter with 0.
    obj_counter = { 
        PGIE_CLASS_ID_VEHICLE:0,
        PGIE_CLASS_ID_PERSON:0,
        PGIE_CLASS_ID_BICYCLE:0,
        PGIE_CLASS_ID_ROADSIGN:0
    }
    num_rects=0
    gst_buffer = info.get_buffer()
    if not gst_buffer:
        print("Unable to get GstBuffer ")
        return

    # Retrieve batch metadata from the gst_buffer
    # Note that pyds.gst_buffer_get_nvds_batch_meta() expects the
    # C address of gst_buffer as input, which is obtained with hash(gst_buffer)
    batch_meta = pyds.gst_buffer_get_nvds_batch_meta(hash(gst_buffer))
    
    # buf_surface = pyds.get_nvds_buf_surface(hash(gst_buffer))
    l_frame = batch_meta.frame_meta_list
    while l_frame is not None:
        try:
            # Note that l_frame.data needs a cast to pyds.NvDsFrameMeta
            # The casting is done by pyds.NvDsFrameMeta.cast()
            # The casting also keeps ownership of the underlying memory
            # in the C code, so the Python garbage collector will leave
            # it alone.
            frame_meta = pyds.NvDsFrameMeta.cast(l_frame.data) #new frame            
        except StopIteration:
            break
        
        frame_number = frame_meta.frame_num     #storing the frame number
        camera_id = frame_meta.pad_index        #storing the source id i.e. source from which this metadat is being extracted, it's the pad index of sink pad linked with streammux 
        num_detect = frame_meta.num_obj_meta    #total number of detections made in that frame 

        #creating a dictionary to hold all the metadata of a frame

        frame_dict = {
        'frame_number': frame_number , 
        'total_detect' : num_detect,
        'camera_id' : camera_id,
        'objects': []  # List to hold object dictionaries
    }
        l_obj=frame_meta.obj_meta_list
        n_frame_bbox = None
        while l_obj is not None:
            try:
                # Casting l_obj.data to pyds.NvDsObjectMeta
                obj_meta=pyds.NvDsObjectMeta.cast(l_obj.data)  #new obj
                obj_counter[obj_meta.class_id] += 1

                confidence_score = obj_meta.confidence   #confidence score of detection
                detect_type = obj_meta.obj_label         #detected class       
                # obj_id  =  int(obj_meta.object_id)    Unique ID for tracking the object. @ref UNTRACKED_OBJECT_ID, use this only when you have tracker in your pipeline
                obj_dict =  {
                'detect_type' : detect_type,
                'confidence_score': confidence_score
                }
                frame_dict['objects'].append(obj_dict)
                
            except StopIteration:
                break
            
            try: 
                l_obj=l_obj.next
            except StopIteration:
                break

        # # Acquiring a display meta object. The memory ownership remains in
        # # the C code so downstream plugins can still access it. Otherwise
        # # the garbage collector will claim it when this probe function exits.
        display_meta=pyds.nvds_acquire_display_meta_from_pool(batch_meta)
        display_meta.num_labels = 1
        py_nvosd_text_params = display_meta.text_params[0]
        # Setting display text to be shown on screen
        # Note that the pyds module allocates a buffer for the string, and the
        # memory will not be claimed by the garbage collector.
        # Reading the display_text field here will return the C address of the
        # allocated string. Use pyds.get_string() to get the string content.

        #display content on screen: count of each detected class and frame number
        py_nvosd_text_params.display_text = "Frame Number={} Number of Objects={} Vehicle_count={} Person_count={}".format(frame_number, num_rects, obj_counter[PGIE_CLASS_ID_VEHICLE], obj_counter[PGIE_CLASS_ID_PERSON])

        # Now set the offsets where the string should appear
        py_nvosd_text_params.x_offset = 10
        py_nvosd_text_params.y_offset = 12

        # Font , font-color and font-size
        py_nvosd_text_params.font_params.font_name = "Serif"
        py_nvosd_text_params.font_params.font_size = 10
        # set(red, green, blue, alpha); set to White
        py_nvosd_text_params.font_params.font_color.set(1.0, 1.0, 1.0, 1.0)

        # Text background color
        py_nvosd_text_params.set_bg_clr = 1
        # set(red, green, blue, alpha); set to Black
        py_nvosd_text_params.text_bg_clr.set(0.0, 0.0, 0.0, 1.0)
        # Using pyds.get_string() to get display_text as string
        # print(pyds.get_string(py_nvosd_text_params.display_text))
        pyds.nvds_add_display_meta_to_frame(frame_meta, display_meta)
        try:
            l_frame=l_frame.next
            print(frame_dict)
        except StopIteration:
            break
    return Gst.PadProbeReturn.OK	


def cb_newpad(decodebin, decoder_src_pad,data):
    print("In cb_newpad\n")
    caps=decoder_src_pad.get_current_caps()
    if not caps:
        caps = decoder_src_pad.query_caps()
    gststruct=caps.get_structure(0)
    gstname=gststruct.get_name()
    source_bin=data
    features=caps.get_features(0)

    # Need to check if the pad created by the decodebin is for video and not
    # audio.
    print("gstname=",gstname)
    if(gstname.find("video")!=-1):
        # Link the decodebin pad only if decodebin has picked nvidia
        # decoder plugin nvdec_*. We do this by checking if the pad caps contain
        # NVMM memory features.
        print("features=",features)
        if features.contains("memory:NVMM"):
            # Get the source bin ghost pad
            bin_ghost_pad=source_bin.get_static_pad("src")
            if not bin_ghost_pad.set_target(decoder_src_pad):
                sys.stderr.write("Failed to link decoder src pad to source bin ghost pad\n")
        else:
            sys.stderr.write(" Error: Decodebin did not pick nvidia decoder plugin.\n")

def decodebin_child_added(child_proxy,Object,name,user_data):
    print("Decodebin child added:", name, "\n")
    if(name.find("decodebin") != -1):
        Object.connect("child-added",decodebin_child_added,user_data)

    if "source" in name:
        source_element = child_proxy.get_by_name("source")
        if source_element.find_property('drop-on-latency') != None:
            Object.set_property("drop-on-latency", True)



def create_source_bin(index,uri):
    print("Creating source bin")

    # Create a source GstBin to abstract this bin's content from the rest of the
    # pipeline
    bin_name="source-bin-%02d" %index
    print(bin_name)
    nbin=Gst.Bin.new(bin_name)
    if not nbin:
        sys.stderr.write(" Unable to create source bin \n")

    # Source element for reading from the uri.
    # We will use decodebin and let it figure out the container format of the
    # stream and the codec and plug the appropriate demux and decode plugins.
    
        # use nvurisrcbin to enable file-loop
    uri_decode_bin=Gst.ElementFactory.make("nvurisrcbin", "uri-decode-bin") #using nvurisrcbin to handle input
    uri_decode_bin.set_property("rtsp-reconnect-interval", 50)
    uri_decode_bin.set_property("uri",uri)
    # Connect to the "pad-added" signal of the decodebin which generates a
    # callback once a new pad for raw data has beed created by the decodebin
    uri_decode_bin.connect("pad-added",cb_newpad,nbin)
    uri_decode_bin.connect("child-added",decodebin_child_added,nbin)

    # We need to create a ghost pad for the source bin which will act as a proxy
    # for the video decoder src pad. The ghost pad will not have a target right
    # now. Once the decode bin creates the video decoder and generates the
    # cb_newpad callback, we will set the ghost pad target to the video decoder
    # src pad.
    Gst.Bin.add(nbin,uri_decode_bin)
    bin_pad=nbin.add_pad(Gst.GhostPad.new_no_target("src",Gst.PadDirection.SRC))
    if not bin_pad:
        sys.stderr.write(" Failed to add ghost pad in source bin \n")
        return None
    return nbin


def main(args):
    print(args)
    number_sources=len(args)
    print(number_sources)

    # Standard GStreamer initialization
    GObject.threads_init()
    Gst.init(None)

    # Create gstreamer elements */
    # Create Pipeline element that will form a connection of other elements
    print("Creating Pipeline \n ")
    pipeline = Gst.Pipeline()
    is_live = False

    if not pipeline:
        sys.stderr.write(" Unable to create Pipeline \n")
    print("Creating streamux \n ")

    # Create nvstreammux instance to form batches from one or more sources.
    streammux = Gst.ElementFactory.make("nvstreammux", "Stream-muxer")
    if not streammux:
        sys.stderr.write(" Unable to create NvStreamMux \n")

    pipeline.add(streammux)
    for i in range(number_sources):

        print("Creating source_bin ",i," \n ")
        uri_name = args[i]

        if uri_name.find("rtsp://") == 0 :
            is_live = True
        else:
            uri_name = "file://"+uri_name
        
        source_bin=create_source_bin(i, uri_name)
        pipeline.add(source_bin)
      
        padname="sink_%u" %i
        sinkpad= streammux.get_request_pad(padname) 
        if not sinkpad:
            sys.stderr.write("Unable to create sink pad bin \n")
        srcpad=source_bin.get_static_pad("src")
        if not srcpad:
            sys.stderr.write("Unable to create src pad bin \n")
        srcpad.link(sinkpad)

    print("creating nvvideoconvert")
    nvvidconv = Gst.ElementFactory.make("nvvideoconvert","nvvidconv")
    if not nvvidconv:
        sys.stderr.write(" Unable to create nvvideoconvert \n")

    nvvidconv1 = Gst.ElementFactory.make("nvvideoconvert", "nvvidconv1")
    if not nvvidconv1:
        sys.stderr.write(" Unable to create nvvideoconvert \n")
        
    print("Creating Pgie \n ")
    pgie = Gst.ElementFactory.make("nvinfer", "primary-inference")
    if not pgie:
        sys.stderr.write(" Unable to create pgie \n")

    print("Creating nvdsosd \n ")
    nvosd = Gst.ElementFactory.make("nvdsosd", "osd")
    if not nvosd:
        sys.stderr.write(" Unable to create nvosd \n")

    print("Creating tiler \n ")
    nvtiler = Gst.ElementFactory.make("nvmultistreamtiler", "nvtiler")
    if not nvtiler:
        sys.stderr.write(" Unable to create tiler \n")
    
    print("Creating encoder \n ")
    encoder = Gst.ElementFactory.make("nvv4l2h264enc", "encoder") 
    if not encoder:
        sys.stderr.write(" Unable to create encoder \n")
    
    print("Creating mpeg-ts muxer \n ")
    container = Gst.ElementFactory.make("mpegtsmux", "mux")
    if not container:
        sys.stderr.write(" Unable to create container \n")

    print("Creating parser \n ")
    parser = Gst.ElementFactory.make("h264parse", "parser") 
    if not parser:
        sys.stderr.write(" Unable to create parser \n")
    
    print("Creating Sink \n")
    sink = Gst.ElementFactory.make("hlssink","sink")
    if not sink:
        sys.stderr.write(" Unable to create sink \n")

    
    print("Creating capsfilter \n")

    capsfilter = Gst.ElementFactory.make("capsfilter", "capsfilter0")
    if not capsfilter:
        sys.stderr.write(" Unable to create capsfilter0 \n")
    caps = Gst.Caps.from_string("video/x-raw(memory:NVMM), width=1280, height=720")
    capsfilter.set_property("caps", caps)

    capsfilter_osd = Gst.ElementFactory.make("capsfilter", "caps_osd")
    caps_osd = Gst.Caps.from_string("video/x-raw(memory:NVMM), width=1280, height=720")
    capsfilter_osd.set_property("caps", caps_osd)

    queue = Gst.ElementFactory.make("queue", "queue_1")
    


    #setting the properties to streammux, nvtiler, encoder and sink
    
    streammux.set_property('gpu-id', 0)
    streammux.set_property('enable-padding', 0)
    streammux.set_property('width', 1280)
    streammux.set_property('height', 720)
    streammux.set_property('batch-size', number_sources) 
    streammux.set_property('batched-push-timeout', 4000000)
    pgie.set_property('config-file-path', 'config.txt')
    # pgie_batch_size=pgie.get_property("batch-size")
    # if(pgie_batch_size != number_sources):
    #     print("WARNING: Overriding infer-config batch-size",pgie_batch_size," with number of sources ", number_sources," \n")
    # pgie.set_property("batch-size", number_sources)

    encoder.set_property("bitrate", 1800000)
    if is_aarch64():
        encoder.set_property("preset-level", "FastPreset")
    else:
        encoder.set_property("preset-id", 2)
    

    nvtiler_rows=int(math.sqrt(number_sources))
    nvtiler_columns=int(math.ceil((1.0*number_sources)/nvtiler_rows))
    nvtiler.set_property("rows",nvtiler_rows)
    nvtiler.set_property("columns",nvtiler_columns)
    nvtiler.set_property("width", TILED_OUTPUT_WIDTH)
    nvtiler.set_property("height", TILED_OUTPUT_HEIGHT)

    nvosd.set_property("process-mode", OSD_PROCESS_MODE)
    nvosd.set_property("display-text", OSD_DISPLAY_TEXT)

    sink.set_property('playlist-root', 'http://localhost:8999/Hls_output/stream_data') # Location of the playlist to write
    sink.set_property('playlist-location', f'{video_info}/low_bitrate.m3u8') # Location where .m3u8 playlist file will be stored
    sink.set_property('location',  f'{video_info}/low_bitrate_segment.%01d.ts')  # Location whee .ts segmentrs will be stored
    sink.set_property('target-duration', 3) # The target duration in seconds of a segment/file. (0 - disabled, useful for management of segment duration by the streaming server)
    sink.set_property('playlist-length', 3) # Length of HLS playlist. To allow players to conform to section 6.3.3 of the HLS specification, this should be at least 3. If set to 0, the playlist will be infinite.
    sink.set_property('max-files', 6) # Maximum number of files to keep on disk. Once the maximum is reached,old files start to be deleted to make room for new ones.


    if not is_aarch64():
        mem_type = int(pyds.NVBUF_MEM_CUDA_UNIFIED)
        streammux.set_property("nvbuf-memory-type", mem_type)
        nvvidconv.set_property("nvbuf-memory-type", mem_type)
        nvtiler.set_property("nvbuf-memory-type", mem_type)
        nvvidconv1.set_property("nvbuf-memory-type", mem_type)
        
     
    
    #adding elements to the pipeline
    print("Adding elements to Pipeline \n")
    pipeline.add(pgie)
    pipeline.add(nvtiler)
    pipeline.add(queue)
    pipeline.add(nvvidconv)
    pipeline.add(nvvidconv1)
    pipeline.add(capsfilter)
    pipeline.add(nvosd)
    pipeline.add(capsfilter_osd)
    pipeline.add(encoder)
    pipeline.add(parser)
    pipeline.add(container)
    pipeline.add(sink)

    
    
    #linking all the elements
    print("Linking elements in the Pipeline \n")
    streammux.link(queue)
    queue.link(pgie)
    pgie.link(nvtiler)
    nvtiler.link(nvosd)
    nvosd.link(nvvidconv1)
    nvvidconv1.link(capsfilter)
    capsfilter.link(encoder)
    encoder.link(parser)
    parser.link(container)
    container.link(sink)


    # create an event loop and feed gstreamer bus mesages to it
    loop = GLib.MainLoop()
    bus = pipeline.get_bus()
    bus.add_signal_watch()
    bus.connect ("message", bus_call, loop)

    
    #a probe function to extract metdata from inferenced frames
    pgie_src_pad=pgie.get_static_pad("src")
    if not pgie_src_pad:
        sys.stderr.write(" Unable to get src pad \n")
    else:
        pgie_src_pad.add_probe(Gst.PadProbeType.BUFFER, pgie_src_pad_buffer_probe, 0)


    # Listing the sources
    print("Now playing...")
    for i, source in enumerate(args):
        if (i != 0):
            print(i, ": ", source)

######################################################################
    print("Starting pipeline \n")
    # start play back and listed to events		
    pipeline.set_state(Gst.State.PLAYING)
    try:
        loop.run()
    except:
        pass
        
    print("Exiting app\n")
    pipeline.set_state(Gst.State.NULL)

if __name__ == "__main__":

    input_list = ["you RTSP link/Links or Video File Path/Paths here, each inside double quotes and comma separated if more than 1"]
    main(input_list)


