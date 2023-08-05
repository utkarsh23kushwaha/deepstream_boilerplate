# Nvidia_Deepstream_BoilerPlate
1. This is an Nvidia Deepstream App, which takes in input in the form of RTSP links, or file paths, performs object detection using the Resnet10 Caffemodel (4 class detection), available in Nvidia DeepStream's sample model folder, streams the final output via HLS and prints the metadata of frames and detected object. Which you can use a boiler plate to develop even more complex Deepstream video analytics pipelines

# Requiremenets
1. Machine with Ubuntu OS and Nvdida GPU or Jetson Devices <br>
2. Gstreamer, DeepstreamSDK and its python bindings should be installed before running the script ([see here](https://github.com/utkarsh23kushwaha/1click_install_DS)) <br>
3. Add RTSP links or file paths, in the input list, in the prescribed format and run main.py 
