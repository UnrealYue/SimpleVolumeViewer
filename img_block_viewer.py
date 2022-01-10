#!/usr/bin/env python3

# A simple viewer based on PyVTK for volumetric data, 
# specialized for neuron tracing.

# Usages:
# python img_block_viewer.py --filepath RM006_s128_c13_f8906-9056.tif
# ./img_block_viewer.py --filepath z00060_c3_2.ims --level 3 --range '[400:800, 200:600, 300:700]' --colorscale 10
# ./img_block_viewer.py --filepath 3864-3596-2992_C3.ims --colorscale 10 --swc R2-N1-A2.json.swc_modified.swc --fibercolor green
# ./img_block_viewer.py --scene scene_example_vol_swc.json

# Program logic:
#   In a very general sense, this code does the following:
#     * Read the window configuration and scene object description.
#     * Load the image or SWC data.
#     * Pass the data to VTK for rendering.
#     * Let VTK to handle the GUI interaction.
#   So this code essentally translate the object descriptinon to VTK command
#   and does the image data loading.

# Code structure text order:
#   General utilizer functions.
#   Image loaders.
#   SWC loaders.
#   VTK related utilizer functions.
#   Keyboard and mouse interaction.
#   GUI control class
#     Loads window settings, object properties, objects.
#   Commandline related data import function.
#   Main.

# Ref.
# Python Wrappers for VTK
# https://vtk.org/doc/nightly/html/md__builds_gitlab_kitware_sciviz_ci_Documentation_Doxygen_PythonWrappers.html

# Demonstrates physically based rendering using image based lighting and a skybox.
# https://kitware.github.io/vtk-examples/site/Python/Rendering/PBR_Skybox/

import os
import time
import json
import pprint

import numpy as np
from numpy import sin, cos, pi
from numpy import array as _a

import tifffile
import h5py

# noinspection PyUnresolvedReferences
import vtkmodules.vtkInteractionStyle
import vtkmodules.vtkRenderingOpenGL2
import vtkmodules.vtkRenderingVolumeOpenGL2
import vtkmodules.vtkRenderingFreeType

from vtkmodules.vtkCommonCore import (
    vtkPoints,
    VTK_CUBIC_INTERPOLATION
)
from vtkmodules.vtkCommonColor import vtkNamedColors
from vtkmodules.vtkCommonDataModel import (
    vtkPiecewiseFunction,
    vtkCellArray,
    vtkPolyData,
    vtkPolyLine
)
from vtkmodules.vtkIOImage import (
    vtkPNGWriter,
    vtkImageImport
)
from vtkmodules.vtkInteractionStyle import (
    vtkInteractorStyleTrackballCamera,
    vtkInteractorStyleFlight,
    vtkInteractorStyleTerrain,
    vtkInteractorStyleUser
)
from vtkmodules.vtkInteractionWidgets import vtkOrientationMarkerWidget
from vtkmodules.vtkRenderingAnnotation import vtkAxesActor
from vtkmodules.vtkCommonTransforms import vtkTransform
from vtkmodules.vtkRenderingCore import (
    vtkColorTransferFunction,
    vtkRenderWindow,
    vtkRenderWindowInteractor,
    vtkRenderer,
    vtkVolume,
    vtkVolumeProperty,
    vtkWindowToImageFilter,
    vtkActor,
    vtkPolyDataMapper,
    vtkPropPicker,
    vtkPointPicker
)
from vtkmodules.vtkRenderingVolume import (
    vtkFixedPointVolumeRayCastMapper,
    vtkGPUVolumeRayCastMapper
)
# 
# noinspection PyUnresolvedReferences
from vtkmodules.vtkRenderingVolumeOpenGL2 import vtkOpenGLRayCastImageDisplayHelper

from vtkmodules.vtkFiltersSources import vtkSphereSource

from vtkmodules.vtkFiltersHybrid import vtkPolyDataSilhouette

from vtk.util.numpy_support import numpy_to_vtk, vtk_to_numpy

def DefaultGUIConfig():
    d = {
        "window": {
            "size": [2400, 1800],
            "title": "SimpleRayCast",
            "number_of_layers": 2
        },

        "renderers":{
            "0":{
                "layer": 0
            },
            "1":{
                "layer": 1,
                "view_port": [0.0, 0.0, 0.2, 0.2]
            }
        }
    }
    return d

def DefaultSceneConfig():
    d = {
        "object_properties": {
            "volume": {
                "opacity_transfer_function": {
                    "AddPoint": [
                        [20, 0.0],
                        [255, 0.2]
                    ],
                    "opacity_scale": 40.0
                },
                "color_transfer_function": {
                    "AddRGBPoint": [
                        [0.0, 0.0, 0.0, 0.0],
                        [64.0, 1.0, 0.0, 0.0],
                        [128.0, 0.0, 0.0, 1.0],
                        [192.0, 0.0, 1.0, 0.0],
                        [255.0, 0.0, 0.2, 0.0]
                    ],
                    "trans_scale": 40.0
                },
                "interpolation": "cubic"
            }
        },

        "objects": {
            "background": {
                "type": "Background",
                "color": "Wheat"
            },
            "3d_cursor": {
                "type": "Sphere",
            },
            "camera1": {
                "type": "Camera",
                "renderer": "0",
                "Azimuth": 45,
                "Elevation": 30,
                "clipping_range": [0.01, 10000]
            },
            "camera2": {
                "type": "Camera",
                "renderer": "1",
                "follow_direction": "camera1"
            },
            "orientation_axes": {
                "type": "AxesActor",
                "ShowAxisLabels": False,
                "renderer": "1",
            },
#            "axes": {
#                "type": "AxesActor",
#                "ShowAxisLabels": False,
#                "length": [100,100,100],
#                "renderer": "0"
#            },
#            "orientation": {
#                "type": "OrientationMarker",
#                "ShowAxisLabels": False,
#                "renderer": "0"
#            },
#            "volume": {
#                "type": "volume",
#                "property": "volume"
#                "mapper": "GPUVolumeRayCastMapper",
#                "view_point": "auto",
#                "file_path": file_path,
#                "origin": [100, 200, 300],
#                "rotation_matrix": [1,0,0, 0,1,0, 0,0,1],
#            }
        }
    }
    return d

debug_level = 4

# Used for print error, controlled by debug_level.
# higher debug_level will show more info.
# 0 == debug_level will show no info.
def dbg_print(level, *p, **keys):
    if level > debug_level:
        return
    level_str = {1:"Error", 2:"Warning", 3:"Hint", 4:"Message", 5:"Verbose"}
    print(level_str[level] + ":", *p, **keys)

def str2array(s):
    if not isinstance(s, str):
        return s
    return [float(it) for it in s[1:-1].split(',')]

def _mat3d(d):
    return np.array(d, dtype=np.float64).reshape(3,3)

def vtkMatrix2array(vtkm):
    # also use self.cam_m.GetData()[i+4*j]?
    m = np.array(
            [
                [vtkm.GetElement(i,j) for j in range(4)]
                for i in range(4)
            ], dtype=np.float64)
    return m

# Utilizer to convert a fraction to integer range
# mostly copy from VISoR_select_light/pick_big_block/volumeio.py
# Examples:
#   rg=[(1, 2)], max_pixel=100: return ( 0,  50)
#   rg=[(2, 2)], max_pixel=100: return (50, 100)
#   rg=[],       max_pixel=100: return (0, 100)
#   rg=(0, 50),  max_pixel=100: return ( 0,  50)
#   rg=([0.1], [0.2]), max_pixel=100: return ( 10,  20)
def rg_part_to_pixel(rg, max_pixel):
    if len(rg) == 0:
        return (0, max_pixel)
    elif len(rg)==1 and len(rg[0])==2:
        # in the form rg=[(1, 2)], it means 1/2 part of a range
        rg = rg[0]
        erg = (int((rg[0]-1)/rg[1] * max_pixel), 
               int((rg[0]  )/rg[1] * max_pixel))
        return erg
    elif len(rg)==2 and isinstance(rg[0], (list, tuple)):
        # in the form rg=([0.1], [0.2]), means 0.1~0.2 part of a range
        p0, p1 = rg[0][0], rg[1][0]
        erg = [int(p0 * max_pixel), int(p1 * max_pixel)]
        return erg
    else:  # return as-is
        return rg

def slice_from_str(slice_str):
    # Construct array slice object.
    # Ref: https://stackoverflow.com/questions/680826/python-create-slice-object-from-string
    # Format example: [100:400, :, 20:]
    dim_ranges = slice_str[1:-1].split(',')
    # convert a:b:c to slice(a,b,c)
    dim_ranges = tuple(
                     slice(
                         *map(
                             lambda x: int(x.strip())
                                 if x.strip() else None,
                             rg.split(':')
                         ))
                     for rg in dim_ranges
                 )
    return dim_ranges

# return a name not occur in name_set
def GetNonconflitName(prefix, name_set):
    i = 1
    name = prefix
    while name in name_set:
        name = prefix + ".%.3d"%i
        i += 1
    return name

def MergeFullDict(d_contain, d_update):
    # update dict d_contain by d_update
    # i.e. overwrite d_contain for items exist in d_update
    # Ref. https://stackoverflow.com/questions/38987/how-do-i-merge-two-dictionaries-in-a-single-expression-take-union-of-dictionari
    def DeepUpdate(d_contain, d_update):
        for key, value in d_update.items(): 
            if key not in d_contain:
                d_contain[key] = value
            else:  # key in d_contain
                if isinstance(value, dict):
                    DeepUpdate(d_contain[key], value)
                else:  # overwirte
                    # simple sanity check: data type must agree
                    if type(d_contain[key]) == type(value):
                        d_contain[key] = value
                    else:
                        dbg_print(2, "DeepUpdate()", "key type mismatch! value discard.")
        return d_contain

    DeepUpdate(d_contain, d_update)

    return d_contain

# copy from volumeio.py
# Read tiff file, return images and meta data
def read_tiff(tif_path, as_np_array = True):
    # see also https://pypi.org/project/tifffile/
    tif = tifffile.TiffFile(tif_path)
    metadata = {tag_val.name:tag_val.value 
                for tag_name, tag_val in tif.pages[0].tags.items()}
    if hasattr(tif, 'imagej_metadata'):
        metadata['imagej'] = tif.imagej_metadata
    if as_np_array:
        images = tifffile.imread(tif_path)
    else:
        images = []
        for page in tif.pages:
            images.append(page.asarray())

    # TODO: determing this value automatically
    metadata['oblique_image'] = True if metadata['ImageLength']==788 else False

    return images, metadata

# Read tiff file, return images and meta data
# Returm image array and metadata.
def read_tiff_meta(tif_path):
    # see also https://pypi.org/project/tifffile/
    tif = tifffile.TiffFile(tif_path)
    metadata = {tag_name:tag_val.value 
                for tag_name, tag_val in tif.pages[0].tags.items()}
    if hasattr(tif, 'imagej_metadata'):
        metadata['imagej'] = tif.imagej_metadata
    return metadata

# Read Imaris compatible image file.
# Returm image array and metadata.
def read_ims(ims_path, extra_conf = {}, cache_reader_obj = False):
    # TODO: how to impliment cache_reader_obj?
    ims = h5py.File(ims_path, 'r')
    level      = int(extra_conf.get('level', 0))
    channel    = int(extra_conf.get('channel', 0))
    time_point = int(extra_conf.get('time_point', 0))
    img = ims['DataSet']['ResolutionLevel %d'%(level)] \
                        ['TimePoint %d'%(time_point)] \
                        ['Channel %d'%(channel)]['Data']
    dbg_print(4, 'image shape: ', img.shape, ' dtype =', img.dtype)

    # convert metadata in IMS to python dict
    img_info = ims['DataSetInfo']
    metadata = {'read_ims':
        {'level': level, 'channel': channel, 'time_point': time_point}}
    for it in img_info.keys():
        metadata[it] = \
            {k:''.join([c.decode('utf-8') for c in v])
                for k, v in img_info[it].attrs.items()}

    dbg_print(4, 'read_ims(): extra_conf =', extra_conf)
    dim_ranges = slice_from_str(str(extra_conf.get('range', '[:,:,:]')))
    dbg_print(4, 'dim_ranges', dim_ranges)
    
    t0 = time.time()
    img_clip = np.array(img[dim_ranges])         # actually read the data
    dbg_print(4, "read_ims(): img read time: %6.3f" % (time.time()-t0))
    #img_clip = np.transpose(np.array(img_clip), (2,1,0))

    metadata['imagej'] = {'voxel_size_um': '(1.0, 1.0, 1.0)'}
    metadata['oblique_image'] = False

    return img_clip, metadata

def Read3DImageDataFromFile(file_name, *item, **keys):
    if file_name.endswith('.tif') or file_name.endswith('.tiff'):
        img_arr, img_meta = read_tiff(file_name)
    elif file_name.endswith('.ims'):
        img_arr, img_meta = read_ims(file_name, *item, **keys)
    dbg_print(5, pprint.pformat(img_meta))
    return img_arr, img_meta

# import image to vtkImageImport() to have a connection
# img_arr must be a numpy-like array
#   dimension order: Z C Y X  (full form TZCYXS)
# img_meta may contain
#   img_meta['imagej']['voxel_size_um']
#   img_meta['oblique_image']
def ImportImageArray(img_arr, img_meta):
    # Ref:
    # Numpy 3D array into VTK data types for volume rendering?
    # https://discourse.vtk.org/t/numpy-3d-array-into-vtk-data-types-for-volume-rendering/3455/2
    # VTK Reading 8-bit tiff files (solved) VTK4.2
    # https://public.kitware.com/pipermail/vtkusers/2003-November/020884.html

    # code from Slicer
    # https://github.com/Slicer/Slicer/blob/2515768aaf70c161d781ff41f36f2a0655c88efb/Base/Python/slicer/util.py#L1950
    # def updateVolumeFromArray(volumeNode, img_arr):

    # See https://python.hotexamples.com/examples/vtk/-/vtkImageImport/python-vtkimageimport-function-examples.html

    dbg_print(4, 'ImportImageArray(): importing image of size:',  img_arr.shape)

    # Wild guess number of channels
    if len(img_arr.shape) == 4:
        n_ch = img_arr.shape[1]
    else:
        n_ch = 1

    if (img_meta is not None) and ('imagej' in img_meta) and \
       (img_meta['imagej'] is not None) and \
       ('voxel_size_um' in img_meta['imagej']):
        if isinstance(img_meta['imagej']['voxel_size_um'], str):
            voxel_size_um = img_meta['imagej']['voxel_size_um'][1:-1]
            voxel_size_um = tuple(map(float, voxel_size_um.split(', ')))
        else:  # assume array
            voxel_size_um = img_meta['imagej']['voxel_size_um']
    else:
        voxel_size_um = (1.0, 1.0, 1.0)

    img_importer = vtkImageImport()
    simg = np.ascontiguousarray(img_arr, img_arr.dtype)  # maybe .flatten()?
    # see also: SetImportVoidPointer
    img_importer.CopyImportVoidPointer(simg.data, simg.nbytes)
    if img_arr.dtype == np.uint8:
        img_importer.SetDataScalarTypeToUnsignedChar()
    elif img_arr.dtype == np.uint16:
        img_importer.SetDataScalarTypeToUnsignedShort()
    else:
        raise "Unsupported format"
    img_importer.SetNumberOfScalarComponents(n_ch)
    img_importer.SetDataExtent (0, simg.shape[2]-1, 0, simg.shape[1]-1, 0, simg.shape[0]-1)
    img_importer.SetWholeExtent(0, simg.shape[2]-1, 0, simg.shape[1]-1, 0, simg.shape[0]-1)

    # the 3x3 matrix to rotate the coordinates from index space (ijk) to physical space (xyz)
    b_oblique_correction = img_meta.get('oblique_image', False)
    dbg_print(4, 'b_oblique_correction: ', b_oblique_correction)
    if b_oblique_correction:
        img_importer.SetDataSpacing(voxel_size_um[0], voxel_size_um[1],
                                    voxel_size_um[2]*np.sqrt(2))
        rotMat = [ \
            1.0, 0.0,            0.0,
            0.0, cos(45/180*pi), 0.0,
            0.0,-sin(45/180*pi), 1.0
        ]
        img_importer.SetDataDirection(rotMat)
    else:
        img_importer.SetDataSpacing(voxel_size_um)

    return img_importer

# Import image to vtkImageImport() to have a connection.
# extra_conf for extra setting to extract the image
# the extra_conf takes higher priority than meta data in the file
def ImportImageFile(file_name, extra_conf = None):
    img_arr, img_meta = Read3DImageDataFromFile(file_name, extra_conf)
    img_import = ImportImageArray(img_arr, img_meta)
    return img_import

# Load tracing result.
def LoadSWCTree(filepath):
    d = np.loadtxt(filepath)
    tr = (np.int32(d[:,np.array([0,6,1])]),
          np.float64(d[:, 2:6]))
    # tree format
    # (id, parent_id, type), ...
    # (x,y,z,diameter), ...
    return tr

# Split the tree in swc into linear segments (i.e. processes).
# return processes in index of tr.
# tr = LoadSWCTree(name)
def SplitSWCTree(tr):
    # Decompose tree to line objects
    # Assume tr is well and sorted and contain only one tree

    # re-label index in tr, s.t. root is 0 and all followings continued
    tr_idx = tr[0].copy()
    max_id = max(tr_idx[:,0])   # max occur node index
    n_id = tr_idx.shape[0]      # number of nodes
    # relabel array (TODO: if max_id >> n_id, we need a different algo.)
    arr_full = np.zeros(max_id+2, dtype=np.int32)
    arr_full[-1] = -1
    arr_full[tr_idx[:,0]] = np.arange(n_id, dtype=np.int32)
    tr_idx[:,0:2] = arr_full[tr_idx[:,0:2]]
    # find branch points
    n_child,_ = np.histogram(tr_idx[1:,1], bins=np.arange(n_id, dtype=np.int32))
    n_child = np.array(n_child, dtype=np.int32)
    # n_child == 0: leaf
    # n_child == 1: middle of a path or root
    # n_child >= 2: branch point
    id_bounds = np.nonzero(n_child-1)[0]
    processes = []
    for eid in id_bounds:
        # travel from leaf to branching point or root
        i = eid
        filament = [i]
        i = tr_idx[i, 1]  # parent
        while n_child[i] == 1 and i != -1:
            filament.append(i)
            i = tr_idx[i, 1]  # parent
        if i != -1:
            filament.append(i)
        processes.append(filament[::-1])

    return processes

def UpdatePropertyOTFScale(obj_prop, otf_s):
    pf = obj_prop.GetScalarOpacity()
    if hasattr(obj_prop, 'ref_prop'):
        obj_prop = obj_prop.ref_prop
    otf_v = obj_prop.prop_conf['opacity_transfer_function']['AddPoint']
    
    # initialize an array of array
    # get all control point coordinates
    v = np.zeros((pf.GetSize(), 4))
    for k in range(pf.GetSize()):
        pf.GetNodeValue(k, v[k])

    if otf_s is None:  # return old otf and current setting
        return otf_v, v

    for k in range(pf.GetSize()):
        v[k][0] = otf_s * otf_v[k][0]
        pf.SetNodeValue(k, v[k])

def UpdatePropertyCTFScale(obj_prop, ctf_s):
    ctf = obj_prop.GetRGBTransferFunction()
    # get all control point coordinates
    # location (X), R, G, and B values, midpoint (0.5), and sharpness(0) values

    if hasattr(obj_prop, 'ref_prop'):
        obj_prop = obj_prop.ref_prop
    ctf_v = obj_prop.prop_conf['color_transfer_function']['AddRGBPoint']
    
    # initialize an array of array
    # get all control point coordinates
    v = np.zeros((ctf.GetSize(), 6))
    for k in range(ctf.GetSize()):
        ctf.GetNodeValue(k, v[k])

    if ctf_s is None:  # return old ctf and current setting
        return ctf_v, v

    for k in range(ctf.GetSize()):
        v[k][0] = ctf_s * ctf_v[k][0]
        ctf.SetNodeValue(k, v[k])

def GetColorScale(obj_prop):
    # guess values of colorscale for otf and ctf
    otf_v, o_v = UpdatePropertyOTFScale(obj_prop, None)
    ctf_v, c_v = UpdatePropertyCTFScale(obj_prop, None)
    return o_v[-1][0] / otf_v[-1][0], c_v[-1][0] / ctf_v[-1][0]

def SetColorScale(obj_prop, scale):
    dbg_print(4, 'Setting colorscale =', scale)
    if hasattr(scale, '__iter__'):
        otf_s = scale[0]
        ctf_s = scale[1]
    else:  # scalar
        otf_s = ctf_s = scale
    UpdatePropertyOTFScale(obj_prop, otf_s)
    UpdatePropertyCTFScale(obj_prop, ctf_s)

def ReadGUIConfigure(gui_conf_path):
    conf = DefaultGUIConfig()
    if os.path.isfile(gui_conf_path):
        conf_ext = json.loads(open(gui_conf_path).read())
        MergeFullDict(conf, conf_ext)
    return conf

def ReadScene(scene_file_path):
    scene = DefaultSceneConfig()
    if os.path.isfile(scene_file_path):
        scene_ext = json.loads(open(scene_file_path).read())
        MergeFullDict(scene, scene_ext)
    return scene

def ShotScreen(render_window):
    # Take a screenshot
    # From: https://kitware.github.io/vtk-examples/site/Python/Utilities/Screenshot/
    win2if = vtkWindowToImageFilter()
    win2if.SetInput(render_window)
    win2if.SetInputBufferTypeToRGB()
    win2if.ReadFrontBufferOff()
    win2if.Update()

    # If need transparency in a screenshot
    # https://stackoverflow.com/questions/34789933/vtk-setting-transparent-renderer-background
    
    writer = vtkPNGWriter()
    writer.SetFileName('TestScreenshot.png')
    writer.SetInputConnection(win2if.GetOutputPort())
    writer.Write()

# Align cam2 by cam1
# make cam2 dist away from origin
def AlignCameraDirection(cam2, cam1, dist=4.0):
    r = np.array(cam1.GetPosition()) - np.array(cam1.GetFocalPoint())
    r = r / np.linalg.norm(r) * dist

    cam2.SetRoll(cam1.GetRoll())
    cam2.SetPosition(r)
    cam2.SetFocalPoint(0, 0, 0)
    cam2.SetViewUp(cam1.GetViewUp())

def CameraFollowCallbackFunction(caller, ev):
    cam1 = CameraFollowCallbackFunction.cam1
    cam2 = CameraFollowCallbackFunction.cam2
    AlignCameraDirection(cam2, cam1)
    return

class PointPicker():
    def __init__(self, points, renderer):
        ren_win = renderer.GetRenderWindow()
        cam = renderer.GetActiveCamera()
        self.init(points, cam, ren_win.GetSize())

    def init(self, points, camera, screen_dims):
        self.p = np.array(points, dtype=np.float64)
        # The matrix from cam to world
        # vec_cam = cam_m * vec_world
        # for cam_m =[[u v], inverse of it is:[[u.T  -u.T*v]
        #             [0 1]]                   [0     1    ]]
        self.cam_m = vtkMatrix2array(camera.GetModelViewTransformMatrix())
        self.screen_dims = _a(screen_dims)
        # https://vtk.org/doc/nightly/html/classvtkCamera.html#a2aec83f16c1c492fe87336a5018ad531
        view_angle = camera.GetViewAngle() / (180/np.pi)
        view_length = 2*np.tan(view_angle/2)
        # aspect = width/height
        aspect_ratio = screen_dims[0] / screen_dims[1]
        if camera.GetUseHorizontalViewAngle():
            unit_view_window = _a([view_length, view_length/aspect_ratio])
        else:  # this is the default
            unit_view_window = _a([view_length*aspect_ratio, view_length])
        self.pixel_scale = unit_view_window / _a(screen_dims)

    def PickAt(self, posxy):
        cam_min_view_distance = 0
        selection_angle_tol = 0.01
        p = self.p
        # constructing picker line: r = v * t + o
        o = - self.cam_m[0:3,0:3].T @ self.cam_m[0:3, 3:4]  # cam pos in world
        #   click pos in cam
        posxy_cam = (_a(posxy) - self.screen_dims / 2) * self.pixel_scale
        v = self.cam_m[0:3,0:3].T @ _a([[posxy_cam[0], posxy_cam[1], -1]]).T
        # compute distance from p to the line
        u = p - o
        t = (v.T @ u) / (v.T @ v)
        dist = np.linalg.norm(u - v * t, axis=0)
        angle_dist = dist / t
        
#        print('self.cam_m', self.cam_m)
#        print('posxy', posxy, '   self.screen_dims', self.screen_dims)
#        print('posxy_unit', (_a(posxy) - self.screen_dims / 2)/self.screen_dims)
#        print('self.pixel_scale', self.pixel_scale)
#        
#        print('o', o)
#        print('posxy_cam', posxy_cam)
#        print('v', v)
#        print('t', np.sort(t))
#        print('dist', np.sort(dist))
#        print('angle_dist', np.sort(angle_dist))
        
        # find nearest point
        in_view_tol = (t > cam_min_view_distance) & (angle_dist < selection_angle_tol)
        ID_selected = np.flatnonzero(in_view_tol)
        if ID_selected.size > 0:
            angle_dist_selected = angle_dist[0, ID_selected]
            ID_selected = ID_selected[np.argmin(angle_dist_selected)]
        return ID_selected, p[:, ID_selected]

class PointSetHolder():
    def __init__(self):
        self.points = np.array([[],[],[]], dtype=np.float64)
        self.range_map = {}
    
    def AddPoints(self, points, name):
        self.points = np.append(self.points, points, axis=1)
        # TODO, maybe make it possible to find 'name' by point
    
    def __call__(self):
        return self.points

# Rotate camera
class execSmoothRotation():
    def __init__(self, cam, degree_per_sec):
        self.actor = cam
        self.degree_per_sec = degree_per_sec
        self.time_start = None
        self.time_last_update = self.time_start

    def startat(self, time_start):
        self.time_start = time_start
        self.time_last_update = self.time_start

    def __call__(self, obj, event, time_now):
        if time_now < self.time_start:
            return
        t_last_elapsed = time_now - self.time_last_update
        self.actor.Azimuth(self.degree_per_sec * t_last_elapsed)
        self.time_last_update = time_now
        iren = obj
        iren.GetRenderWindow().Render()
        #print('execSmoothRotation: Ren', time_now - self.time_start)

# Sign up to receive TimerEvent
class timerHandler():
    def __init__(self, interactor, duration, exec_obj):
        self.exec_obj = exec_obj
        self.interactor = interactor
        self.timerId = None
        self.time_start = 0
        self.duration = duration

    def callback(self, obj, event):
        t_now = time.time()
        if t_now - self.time_start > self.duration:
            self.stop()
            # align the time to the exact boundary
            t_now = self.time_start + self.duration
        self.exec_obj(obj, event, t_now)

    def start(self):
        self.interactor.AddObserver('TimerEvent', self.callback)
        self.time_start = time.time()
        self.exec_obj.startat(self.time_start)
        self.timerId = self.interactor.CreateRepeatingTimer(10)
    
    def stop(self):
        if self.timerId:
            self.interactor.DestroyTimer(self.timerId)

    def __del__(self):
        self.stop()

# Deal with keyboard and mouse interactions.
# vtkInteractorStyleTerrain
# vtkInteractorStyleFlight
# vtkInteractorStyleTrackballCamera
# vtkInteractorStyleUser
class MyInteractorStyle(vtkInteractorStyleTerrain):

    def __init__(self, iren, guictrl):
        self.iren = iren
        self.guictrl = guictrl

        # var for picker
        self.picked_actor = None

        # mouse events
        self.fn_modifier = []
        self.AddObserver('LeftButtonPressEvent',
                         self.left_button_press_event)
        self.AddObserver('LeftButtonReleaseEvent',
                         self.left_button_release_event)
        self.AddObserver('MiddleButtonPressEvent',
                         self.middle_button_press_event)
        self.AddObserver('MiddleButtonReleaseEvent',
                         self.middle_button_release_event)
        self.AddObserver('MouseWheelForwardEvent',
                         self.mouse_wheel_event(1))
        self.AddObserver('MouseWheelBackwardEvent',
                         self.mouse_wheel_event(-1))
        self.AddObserver('RightButtonPressEvent',
                         self.right_button_press_event)
        self.AddObserver('RightButtonReleaseEvent',
                         self.right_button_release_event)
        self.left_button_press_event_release_fn = None

        # keyboard events
        self.AddObserver('CharEvent', self.OnChar)

    # To test fully quantified "C" "A" "S".
    def is_kbd_modifier(self, u = ''):
        iren = self.iren
        m = 'C' if iren.GetControlKey() else ' ' + \
            'A' if iren.GetAltKey() else ' ' + \
            'S' if iren.GetShiftKey() else ' '
        u = u.upper()
        p = 'C' if 'C' in u else ' ' + \
            'A' if 'A' in u else ' ' + \
            'S' if 'S' in u else ' '
        return p == m

    def left_button_press_event(self, obj, event):
        if self.is_kbd_modifier(''):
            self.OnLeftButtonDown()
            self.left_button_press_event_release_fn = \
                lambda: self.OnLeftButtonUp()
        elif self.is_kbd_modifier('S'):
            self.OnMiddleButtonDown()
            self.left_button_press_event_release_fn = \
                lambda: self.OnMiddleButtonUp()
    
    def left_button_release_event(self, obj, event):
        if self.left_button_press_event_release_fn:
            self.left_button_press_event_release_fn()
        else:
            self.OnLeftButtonUp()

    def mouse_wheel_event(self, direction):
        def mouse_wheel_action(obj, event, direction = direction):
            win = obj.iren.GetRenderWindow()
            rens = win.GetRenderers()
            rens.InitTraversal()
            ren1 = rens.GetNextItem()
            cam = ren1.GetActiveCamera()
            # modify the distance between camera and the focus point
            fp = _a(cam.GetFocalPoint())
            p  = _a(cam.GetPosition())
            new_p = fp + (p - fp) * (1.2 ** (-direction))
            cam.SetPosition(new_p)
            win.Render()
        return mouse_wheel_action

    def middle_button_press_event(self, obj, event):
        print('Middle Button pressed')
        self.OnMiddleButtonDown()
        return

    def middle_button_release_event(self, obj, event):
        print('Middle Button released')
        self.OnMiddleButtonUp()
        return

    def right_button_press_event(self, obj, event):
        ren = self.guictrl.GetMainRenderer()

        # select object
        # Ref. HighlightWithSilhouette
        # https://kitware.github.io/vtk-examples/site/Python/Picking/HighlightWithSilhouette/
        clickPos = self.iren.GetEventPosition()
        dbg_print(5, 'clicked at', clickPos)

        ppicker = PointPicker(self.guictrl.point_set_holder(), ren)
        pid, pxyz = ppicker.PickAt(clickPos)
        print(pid, pxyz)
        
        picker = vtkPointPicker()
        picker.SetUseCells(False)
        picker.Pick(clickPos[0], clickPos[1], 0, ren)
        p = picker.GetPickPosition()
        dbg_print(4, 'picker point id:', picker.GetPointId ())
#        picker.SetTolerance(0.001)
#        dbg_print(4, 'picker tolerance:', picker.GetTolerance())
        
        #self.guictrl.Set3DCursor([p[0],p[1],p[2]])
        if pxyz.size > 0:
            self.guictrl.Set3DCursor(pxyz)
        
#        picker = vtkPropPicker()
#        picker.Pick(clickPos[0], clickPos[1], 0, ren)
#        self.picked_actor = picker.GetActor()

#        if self.picked_actor and '3d_cursor' in self.guictrl.scene_objects:
#            dbg_print(3, 'Adding silhouette.')
#            self.picked_actor = self.guictrl.scene_objects['3d_cursor']
#
#            silhouette       = self.guictrl.utility_objects['silhouette'][0]
#            silhouette_actor = self.guictrl.utility_objects['silhouette'][1]
#            #ren.RemoveActor(silhouette_actor)
#
#            # Highlight the picked actor by generating a silhouette
#            silhouette.SetInputData(
#                self.picked_actor.GetMapper().GetInput())
#            ren.AddActor(silhouette_actor)

        # purposely no call to self.OnRightButtonDown()
    
    def right_button_release_event(self, obj, event):
        # purposely no call to self.OnRightButtonUp()
        return
    
    def OnChar(self, obj, event):
        iren = self.iren

        key_sym  = iren.GetKeySym()   # useful for PageUp etc.
        key_code = iren.GetKeyCode()
        b_C = iren.GetControlKey()
        b_A = iren.GetAltKey()
        b_S = iren.GetShiftKey()  # sometimes reflected in key_code

        key_combo = ("Ctrl+" if b_C else "") + ("Alt+" if b_A else "") + ("Shift+" if b_S else "") + key_code
        dbg_print(4, 'Pressed:', key_combo, '  key_sym:', key_sym)
        
        is_default_binding = (key_code.lower() in 'jtca3efprsuw') and \
                             not b_C

        #        shift ctrl alt
        #    q    T    F    T
        #    3    F    F    T
        #    e    T    F    T
        #    r    T    F    T

        rens = iren.GetRenderWindow().GetRenderers()
        rens.InitTraversal()
        ren1 = rens.GetNextItem()
        
        if key_combo == 'r':
            ren2 = rens.GetNextItem()
            cam1 = ren1.GetActiveCamera()
            cam2 = ren2.GetActiveCamera()
            rotator = execSmoothRotation(cam1, 60.0)
            timerHandler(iren, 6.0, rotator).start()
        elif (key_sym in ['plus','minus'] or key_combo in '+-') and \
            self.guictrl.selected_objects:
            # Make the image darker or lighter.
            vol_name = self.guictrl.selected_objects[0]  # active object
            vol = self.guictrl.scene_objects[vol_name]
            obj_prop = vol.GetProperty()
            #obj_prop = self.guictrl.object_properties[vol_name]
            cs_o, cs_c = GetColorScale(obj_prop)
            k = np.sqrt(np.sqrt(2))
            if key_sym == 'plus' or key_combo == '+':
                k = 1.0 / k
            SetColorScale(obj_prop, [cs_o*k, cs_c*k])
#            scene_obj = self.guictrl.scene_objects[vol_name]
#            scene_obj.Modified()  # not work
#            scene_obj.Update()
            iren.GetRenderWindow().Render()
        elif key_sym == 's' and not (b_C or b_S or b_A):
            # take a screenshot
            self.guictrl.ShotScreen()
        elif key_combo == ' ':
            # fly to selected object
            vol_name = self.guictrl.selected_objects[0]  # active object
            dbg_print(4, "Fly to:", vol_name)
            vol = self.guictrl.scene_objects[vol_name]
            bd = vol.GetBounds()
            center = [(bd[0]+bd[1])/2, (bd[2]+bd[3])/2, (bd[4]+bd[5])/2]
            iren.FlyTo(ren1, center)
        elif key_sym == 'KP_0':
            cursor = self.guictrl.scene_objects.get('3d_cursor', None)
            if hasattr(cursor, 'world_coor'):
                center = cursor.world_coor
                iren.FlyTo(ren1, center)
            else:
                dbg_print(2, 'OnChar(): no 3d coor found.')

        # Let's say, disable all default key bindings (except q)
        if not is_default_binding:
            super(MyInteractorStyle, obj).OnChar()

class GUIControl:
    def __init__(self):
        # Load configure
        file_name = get_program_parameters()

        self.renderers = {}
        self.render_window = None
        self.interactor = None
        self.object_properties = {}
        self.scene_objects = {}
        self.selected_objects = []
        self.main_renderer_name = None
        
        self.utility_objects = {}
        
        self.point_set_holder = PointSetHolder()
        
        # load default settings
        self.GUISetup(DefaultGUIConfig())
        self.AppendToScene(DefaultSceneConfig())

    def GetNonconflitName(self, name_prefix, name_book = 'scene'):
        if name_book == 'scene':
            index = self.scene_objects
        elif name_book == 'property':
            index = self.object_properties
        return GetNonconflitName(name_prefix, index.keys())

    def GetMainRenderer(self):
        if self.main_renderer_name:
            return self.renderers[self.main_renderer_name]
        elif self.renderers:
            # first one is the main
            self.main_renderer_name = \
                next(iter(self.renderers.keys()))
            return self.renderers[self.main_renderer_name]
        return None

    def UtilizerInit(self):
        colors = vtkNamedColors()
    	
        silhouette = vtkPolyDataSilhouette()
        silhouette.SetCamera(self.GetMainRenderer().GetActiveCamera())

        # Create mapper and actor for silhouette
        silhouetteMapper = vtkPolyDataMapper()
        silhouetteMapper.SetInputConnection(silhouette.GetOutputPort())

        silhouetteActor = vtkActor()
        silhouetteActor.SetMapper(silhouetteMapper)
        silhouetteActor.GetProperty().SetColor(colors.GetColor3d("Tomato"))
        silhouetteActor.GetProperty().SetLineWidth(5)

        self.utility_objects['silhouette'] = [silhouette, silhouetteActor]

    def Set3DCursor(self, xyz):
        # operate on object: 3d_cursor
        if '3d_cursor' in self.scene_objects:
            cursor = self.scene_objects['3d_cursor']
            cursor.world_coor = xyz
            dbg_print(4, "Set 3D cursor to", xyz)
            cursor.SetPosition(xyz)
            self.render_window.Render()

    # setup window, renderers and interactor
    def GUISetup(self, gui_conf):
        dbg_print(4, gui_conf)
        if "window" in gui_conf:
            # TODO: stop the old window?
            # TODO: try vtkVRRenderWindow?
            if self.render_window is None:
                self.render_window = vtkRenderWindow()
            win_conf = gui_conf["window"]
            if "size" in win_conf:
                self.render_window.SetSize(win_conf["size"])
            if "title" in win_conf:
                self.render_window.SetWindowName(win_conf["title"])
            if "number_of_layers" in win_conf:
                self.render_window.SetNumberOfLayers(
                    win_conf["number_of_layers"])

        # Ref: Demonstrates the use of two renderers. Notice that the second (and subsequent) renderers will have a transparent background.
        # https://kitware.github.io/vtk-examples/site/Python/Rendering/TransparentBackground/
        if "renderers" in gui_conf:
            # get our renderer list
            renderers = self.renderers
            # load new renderers
            for key, ren_conf in gui_conf["renderers"].items():
                if key in renderers:
                    # remove old renderer
                    self.render_window.RemoveRenderer(renderers[key])
                # https://kitware.github.io/vtk-examples/site/Python/Rendering/TransparentBackground/
                # setup new renderer
                renderer = vtkRenderer()
                if "layer" in ren_conf:
                    renderer.SetLayer(ren_conf["layer"])
                if "view_port" in ren_conf:
                    renderer.SetViewport(ren_conf["view_port"])
                renderers[key] = renderer
                # add new renderer to window
                self.render_window.AddRenderer(renderer)

        # Create the interactor (for keyboard and mouse)
        interactor = vtkRenderWindowInteractor()
        interactor.SetInteractorStyle(MyInteractorStyle(interactor, self))
    #    interactor.AddObserver('ModifiedEvent', ModifiedCallbackFunction)
        interactor.SetRenderWindow(self.render_window)
        self.interactor = interactor
        
        # first time render, for 'Timer" event to work in Windows
        self.render_window.Render()

    # The property describes how the data will look.
    def AddObjectProperty(self, name, prop_conf):
        if name in self.object_properties:
            # TODO: do we need to remove old mappers?
            dbg_print(2, 'AddObjectProperty(): conflict name: ', name)
        dbg_print(3, 'AddObjectProperty(): "'+name+'" :', prop_conf)
        if name.startswith("volume"):
            volume_property = vtkVolumeProperty()
            
            if 'copy_from' in prop_conf:
                dbg_print(4, 'Copy propperty from', prop_conf['copy_from'])
                # construct a volume property by copying from exist
                ref_prop = self.object_properties[prop_conf['copy_from']]
                volume_property.DeepCopy(ref_prop)
                volume_property.prop_conf = prop_conf
                volume_property.ref_prop = ref_prop
                self.object_properties.update({name: volume_property})
                self.ModifyObjectProperty(name, prop_conf)
                return

            if 'opacity_transfer_function' in prop_conf:
                otf_conf = prop_conf['opacity_transfer_function']
                otf_v = otf_conf['AddPoint']
                otf_s = otf_conf['opacity_scale']
                # Create transfer mapping scalar value to opacity.
                otf = vtkPiecewiseFunction()
                otf.AddPoint(otf_s*otf_v[0][0], otf_v[0][1])
                otf.AddPoint(otf_s*otf_v[1][0], otf_v[1][1])
                volume_property.SetScalarOpacity(otf)

            if 'color_transfer_function' in prop_conf:
                ctf_conf = prop_conf['color_transfer_function']
                ctf_v = ctf_conf['AddRGBPoint']
                ctf_s = ctf_conf['trans_scale']
                ctf_v_e = np.array(ctf_v).copy()
                for v in ctf_v_e:
                    v[0] = v[0] *  ctf_s
                # Create transfer mapping scalar value to color.
                ctf = vtkColorTransferFunction()
                for v in ctf_v_e:
                    ctf.AddRGBPoint(*v)
                volume_property.SetColor(ctf)

            volume_property.ShadeOn()

            if 'interpolation' in prop_conf:
                if prop_conf['interpolation'] == "cubic":
                    volume_property.SetInterpolationType(
                        VTK_CUBIC_INTERPOLATION)
                elif prop_conf['interpolation'] == "linear":
                    volume_property.SetInterpolationTypeToLinear()
                else:
                    dbg_print(2, "AddObjectProperty(): unknown interpolation type")
            volume_property.prop_conf = prop_conf
            object_property = volume_property
        else:
            dbg_print(2, "AddObjectProperty(): unknown object type")

        self.object_properties.update({name: object_property})

    def ModifyObjectProperty(self, name, prop_conf):
        obj_prop = self.object_properties[name]
        dbg_print(4, 'ModifyObjectProperty():', name)
        if name.startswith("volume"):
            if 'opacity_transfer_function' in prop_conf:
                otf_conf = prop_conf['opacity_transfer_function']
                if 'opacity_scale' in otf_conf:
                    otf_s = otf_conf['opacity_scale']
                    UpdatePropertyOTFScale(obj_prop, otf_s)
            if 'color_transfer_function' in prop_conf:
                ctf_conf = prop_conf['color_transfer_function']
                if 'trans_scale' in ctf_conf:
                    ctf_s = ctf_conf['trans_scale']
                    UpdatePropertyCTFScale(obj_prop, ctf_s)

    def AddObjects(self, name, obj_conf):
        if name in self.scene_objects:
            # TODO: do we need to remove old object?
            dbg_print(2, 'AddObjects(): conflict name: ', name)
            name = self.GetNonconflitName(name)

        renderer = self.renderers[
            obj_conf.get('renderer', '0')]

        dbg_print(3, 'AddObjects: "' + name + '" :', obj_conf)
        dbg_print(4, "renderer: ",  obj_conf.get('renderer', '0'))

        if obj_conf['type'] == 'volume':
            file_path = obj_conf['file_path']
            img_importer = ImportImageFile(file_path, obj_conf)
            # set position scaling and direction
            img_importer.SetDataOrigin(obj_conf.get('origin', [0,0,0]))
            # for 3d rotation and scaling
            dir3d = img_importer.GetDataDirection()
            idmat = [1,0,0,0,1,0,0,0,1]
            rot3d = obj_conf.get('rotation_matrix', idmat)
            dir3d = (_mat3d(rot3d) @ _mat3d(dir3d)).flatten()
            img_importer.SetDataDirection(dir3d)

            # vtkVolumeMapper
            # https://vtk.org/doc/nightly/html/classvtkVolumeMapper.html
            mapper_name = obj_conf.get('mapper', 'GPUVolumeRayCastMapper')
            if mapper_name == 'GPUVolumeRayCastMapper':
                volume_mapper = vtkGPUVolumeRayCastMapper()
            elif mapper_name == 'FixedPointVolumeRayCastMapper':
                volume_mapper = vtkFixedPointVolumeRayCastMapper()
            else:
                # TODO: consider use vtkMultiBlockVolumeMapper
                # OR: vtkSmartVolumeMapper https://vtk.org/doc/nightly/html/classvtkSmartVolumeMapper.html#details
                # vtkOpenGLGPUVolumeRayCastMapper
                volume_mapper = vtkGPUVolumeRayCastMapper()
            #volume_mapper.SetBlendModeToComposite()
            volume_mapper.SetInputConnection(img_importer.GetOutputPort())

            # get property used in rendering
            ref_prop_conf = obj_conf.get('property', 'volume')
            if isinstance(ref_prop_conf, dict):
                # add new property
                prop_name = self.GetNonconflitName('volume', 'property')
                dbg_print(3, 'AddObjects(): Adding prop:', prop_name)
                self.AddObjectProperty(prop_name, ref_prop_conf)
                volume_property = self.object_properties[prop_name]
            else:
                dbg_print(3, 'AddObjects(): Using existing prop:', ref_prop_conf)
                volume_property = self.object_properties[ref_prop_conf]

            # The volume holds the mapper and the property and
            # can be used to position/orient the volume.
            volume = vtkVolume()
            volume.SetMapper(volume_mapper)
            volume.SetProperty(volume_property)
            
            renderer.AddVolume(volume)

            view_point = obj_conf.get('view_point', 'auto')
            if view_point == 'auto':
                # auto view all actors
                renderer.ResetCamera()
            
            self.selected_objects = [name]
            scene_object = volume

        elif obj_conf['type'] == 'swc':
            ntree = LoadSWCTree(obj_conf['file_path'])
            processes = SplitSWCTree(ntree)
            
            raw_points = ntree[1][:,0:3]
            self.point_set_holder.AddPoints(raw_points.T, '')
            
            # ref: 
            # https://kitware.github.io/vtk-examples/site/Python/GeometricObjects/PolyLine/
            # https://kitware.github.io/vtk-examples/site/Cxx/GeometricObjects/LinearCellDemo/
            # The procedure to add lines is:
            #    vtkPoints()  ---------------------+> vtkPolyData()
            #    vtkPolyLine() -> vtkCellArray()  /
            #   then
            #    vtkPolyData() -> vtkPolyDataMapper() -> vtkActor() -> 
            #         vtkRenderer()
            
            points = vtkPoints()
            points.SetData( numpy_to_vtk(raw_points, deep=True) )
            
            cells = vtkCellArray()
            for proc in processes:
                polyLine = vtkPolyLine()
                polyLine.GetPointIds().SetNumberOfIds(len(proc))
                for i in range(0, len(proc)):
                    polyLine.GetPointIds().SetId(i, proc[i])
                cells.InsertNextCell(polyLine)

            polyData = vtkPolyData()
            polyData.SetPoints(points)
            polyData.SetLines(cells)

            colors = vtkNamedColors()

            mapper = vtkPolyDataMapper()
            mapper.SetInputData(polyData)
            actor = vtkActor()
            actor.SetMapper(mapper)
            actor.GetProperty().SetColor(
                colors.GetColor3d(obj_conf['color']))
            renderer.AddActor(actor)
            #actor.raw_points = raw_points  # for convenience
            
            scene_object = actor

        elif obj_conf['type'] == 'AxesActor':
            # Create Axes object to indicate the orientation
            # vtkCubeAxesActor()
            # https://kitware.github.io/vtk-examples/site/Python/Visualization/CubeAxesActor/

            # Dynamically change position of Axes
            # https://discourse.vtk.org/t/dynamically-change-position-of-axes/691
            # Method 1
            axes = vtkAxesActor()
            axes.SetTotalLength(obj_conf.get('length', [1.0, 1.0, 1.0]))
            axes.SetAxisLabels(obj_conf.get('ShowAxisLabels', False))

            renderer.AddActor(axes)
            scene_object = axes

        elif obj_conf['type'] == 'Sphere':
            colors = vtkNamedColors()

            sphereSource = vtkSphereSource()
            sphereSource.SetCenter(0.0, 0.0, 0.0)
            sphereSource.SetRadius(2)
            sphereSource.SetPhiResolution(30)
            sphereSource.SetThetaResolution(30)
            
            mapper = vtkPolyDataMapper()
            mapper.SetInputConnection(sphereSource.GetOutputPort())
            
            actor = vtkActor()
            actor.GetProperty().SetColor(colors.GetColor3d("Peacock"))
            actor.GetProperty().SetSpecular(0.6)
            actor.GetProperty().SetSpecularPower(30)
            actor.SetMapper(mapper)
            
            renderer.AddActor(actor)
            scene_object = actor

        elif obj_conf['type'] == 'OrientationMarker':
            # Method 2
            # Ref: https://kitware.github.io/vtk-examples/site/Python/Interaction/CallBack/
            axes = vtkAxesActor()
            axes.SetTotalLength([1.0, 1.0, 1.0])
            axes.SetAxisLabels(obj_conf.get('ShowAxisLabels', False))
            axes.SetAxisLabels(True)

            # Ref: https://vtk.org/doc/nightly/html/classvtkOrientationMarkerWidget.html
            om = vtkOrientationMarkerWidget()
            om.SetOrientationMarker(axes)
            om.SetInteractor(self.interactor)
            om.SetDefaultRenderer(renderer)
            om.EnabledOn()
            om.SetInteractive(False)
            #om.InteractiveOn()
            om.SetViewport(0, 0, 0.2, 0.2)
            # TODO: the vtkOrientationMarkerWidget and timerHandler can cause program lose respons or Segmentation fault, for unknown reason.

            scene_object = om

        elif obj_conf['type'] == 'Background':
            colors = vtkNamedColors()
            renderer.SetBackground(colors.GetColor3d(obj_conf['color']))
            scene_object = renderer

        elif obj_conf['type'] == 'Camera':
            if 'renderer' in obj_conf:
                cam = renderer.GetActiveCamera()
                renderer.ResetCameraClippingRange()
                renderer.ResetCamera()
            else:
                cam = vtk.vtkCamera()

            if ('Azimuth' in obj_conf) or ('Elevation' in obj_conf):
                cam.Azimuth(obj_conf['Azimuth'])
                cam.Elevation(obj_conf['Elevation'])

            if 'clipping_range' in obj_conf:
                cam.SetClippingRange(obj_conf['clipping_range'])

            if 'follow_direction' in obj_conf:
                cam_ref = self.scene_objects[obj_conf['follow_direction']]
                cam.DeepCopy(cam_ref)
                cam.SetClippingRange(0.1, 1000)
                AlignCameraDirection(cam, cam_ref)

                CameraFollowCallbackFunction.cam1 = cam_ref
                CameraFollowCallbackFunction.cam2 = cam

                cam_ref.AddObserver( \
                    'ModifiedEvent', CameraFollowCallbackFunction)

            scene_object = cam

        self.scene_objects.update({name: scene_object})

    # add objects to the renderers
    def AppendToScene(self, scene_conf):
        if "object_properties" in scene_conf:
            for key, prop_conf in scene_conf["object_properties"].items():
                self.AddObjectProperty(key, prop_conf)

        if "objects" in scene_conf:
            for key, obj_conf in scene_conf["objects"].items():
                self.AddObjects(key, obj_conf)
        # see also vtkAssembly
        # https://vtk.org/doc/nightly/html/classvtkAssembly.html#details
        return

    def RemoveObjects(self, name):
        if name not in self.scene_objects:
            dbg_print(2,"RemoveObjects(): object non-exist:", name)
            return
        obj = self.scene_objects[name]
        ren = self.GetMainRenderer()
        re.RemoveActor(obj)
        del self.scene_objects[name]
        # TODO: correctly remove a object, possibly from adding process.

    def EasyObjectImporter(self, obj_desc):
        if not obj_desc:
            return
        if isinstance(obj_desc, str):
            obj_desc = {'filepath': obj_desc}
        
        if 'filepath' in obj_desc:
            file_path = obj_desc['filepath']
            if file_path.endswith('.tif'):
                # assume this a volume
                obj_conf = {
                    "type": "volume",
                    "mapper": "GPUVolumeRayCastMapper",
                    "view_point": "auto",
                    "file_path": file_path
                }
            elif file_path.endswith('.ims') or file_path.endswith('.h5'):
                # assume this a IMS volume
                obj_conf = {
                    "type": "volume",
                    "mapper": "GPUVolumeRayCastMapper",
                    "view_point": "auto",
                    "file_path": file_path,
                    "level": obj_desc.get('level', '0'),
                    "channel": obj_desc.get('channel', '0'),
                    "time_point": obj_desc.get('time_point', '0'),
                    "range": obj_desc.get('range', '[:,:,:]')
                }
            else:
                dbg_print(1, "Unreconized source format.")
                return
            
            if 'origin' in obj_desc:
                obj_conf.update({
                    'origin': str2array(obj_desc['origin'])
                })
            if 'rotation_matrix' in obj_desc:
                obj_conf.update({
                    'rotation_matrix': str2array(obj_desc['rotation_matrix'])
                })
            
            if 'colorscale' in obj_desc:
                s = float(obj_desc['colorscale'])
                obj_conf.update({'property': {
                    'copy_from': 'volume',
                    'opacity_transfer_function': {'opacity_scale': s},
                    'color_transfer_function'  : {'trans_scale': s}
                }})
            else:
                obj_conf.update({'property': 'volume'})

            name = self.GetNonconflitName('volume')
            self.AddObjects(name, obj_conf)
            
        if 'swc' in obj_desc:
            name = self.GetNonconflitName('swc')
            obj_conf = {
                "type": 'swc',
                "color": obj_desc.get('fibercolor','Tomato'),
                "file_path": obj_desc['swc']
            }
            self.AddObjects(name, obj_conf)

    def ShotScreen(self):
        ShotScreen(self.render_window)

    def Start(self):
        self.interactor.Initialize()
        self.render_window.Render()
        self.UtilizerInit()
        self.interactor.Start()

def get_program_parameters():
    import argparse
    description = 'Simple volume image viewer based on PyVTK.'
    epilogue = '''
    Keyboard shortcuts:
        '+'/'-': Make the image darker or lighter;
        'r': Auto rotate the image for a while;
        's': Save a screenshot;
        'q': Exit the program.
    '''
    parser = argparse.ArgumentParser(description=description, epilog=epilogue,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--filepath', help='image stack filepath')
    parser.add_argument('--level', help='for multi-level image (.ims), load only that level')
    parser.add_argument('--channel', help='Select channel for IMS image.')
    parser.add_argument('--time_point', help='Select time point for IMS image.')
    parser.add_argument('--range', help='Select range within image.')
    parser.add_argument('--colorscale', help='Set scale of color transfer function.')
    parser.add_argument('--origin', help='Set origin of the volume.')
    parser.add_argument('--rotation_matrix', help='Set rotation matrix of the volume.')
    parser.add_argument('--swc', help='Read and draw swc file.')
    parser.add_argument('--fibercolor', help='Set fiber color.')
    parser.add_argument('--scene', help='Project scene file path. e.g. for batch object loading.')
    args = parser.parse_args()
    # convert class attributes to dict
    keys = ['filepath', 'level', 'channel', 'time_point', 'range',
            'colorscale', 'swc', 'fibercolor', 'origin', 'rotation_matrix',
            'scene']
    d = {k: getattr(args, k) for k in keys
            if hasattr(args, k) and getattr(args, k)}
    dbg_print(3, 'get_program_parameters(): d=', d)
    return d

if __name__ == '__main__':
    gui = GUIControl()
    cmd_obj_desc = get_program_parameters()
    if 'scene' in cmd_obj_desc:
        # TODO: maybe move this before init of gui, and pass it as init param.
        scene_ext = json.loads(open(cmd_obj_desc['scene']).read())
        gui.AppendToScene(scene_ext)
    gui.EasyObjectImporter(cmd_obj_desc)
    gui.Start()
    
