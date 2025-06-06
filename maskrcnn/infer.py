# Copyright 2022 Huawei Technologies Co., Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ============================================================================

"""Inference for MaskRcnn"""
import os
import time
import random
import colorsys

from mindspore import context, Tensor
from mindspore.train.serialization import load_checkpoint, load_param_into_net
from mindspore.common import set_seed

import cv2
import numpy as np
import matplotlib
# matplotlib.use('TkAgg')
import matplotlib.pyplot as plt
import matplotlib.patches as patches

from src.utils.config import config
from src.model.mask_rcnn_r50 import MaskRcnnResnet50
from src.model.mask_rcnn_mobilenetv1 import MaskRcnnMobilenetv1
from dataset.dataset import create_coco_dataset

set_seed(1)


def get_ax(rows=1, cols=1, size=16):
    """Return a Matplotlib Axes array to be used in
    all visualizations in the notebook. Provide a
    central point to control graph sizes.  
    Adjust the size attribute to control how big to render images
    """
    _, axis = plt.subplots(rows, cols, figsize=(size*cols, size*rows))
    return axis


def mindrecord_to_rgb(img_data):
    """Returns a RGB image from evaluated results.
    """
    index = 0
    convert_img = (-np.min(img_data[index,:,:,:])+img_data[index,:,:,:])\
        *255/(np.max(img_data[index,:,:,:])-np.min(img_data[index,:,:,:]))
    temp_img = convert_img.astype(np.uint8)
    img = np.zeros([config.img_height, config.img_width, 3])
    img[:,:,0] = temp_img[0,:,:]
    img[:,:,1] = temp_img[1,:,:]
    img[:,:,2] = temp_img[2,:,:]
    return img


def random_colors(N, bright=True):
    """
    Generate random colors.
    To get visually distinct colors, generate them in HSV space then
    convert to RGB.
    """
    brightness = 1.0 if bright else 0.7
    hsv = [(i / N, 1, brightness) for i in range(N)]
    colors = list(map(lambda c: colorsys.hsv_to_rgb(*c), hsv))
    random.shuffle(colors)
    return colors


def infer():
    """
    Return Mask RCNN evaluated results.

    Returns:
        output: Mask RCNN evaluated result.
                [Tensor[2,80000,5],
                 Tensor[2,80000,1],
                 Tensor[2,80000,1]
                 Tensor[2,80000,28,28]]
        img: RGB image, (height, width, 3)
    """
    # load image
    context.set_context(mode=context.GRAPH_MODE)

    mindrecord_dir = os.path.join(config.data_root,
                                  config.mindrecord_dir)

    prefix = "MaskRcnn_eval.mindrecord"

    mindrecord_file = os.path.join(mindrecord_dir, prefix)

    dataset = create_coco_dataset(mindrecord_file,
                                  batch_size=config.test_batch_size,
                                  is_training=False)

    total = dataset.get_dataset_size()
    image_id = np.random.choice(total,1)
    print("Dataset size:", total)
    # load model
    ckpt_path = config.checkpoint_path
    net = MaskRcnnResnet50(config)
    # net = MaskRcnnMobilenetv1(config)
    param_dict = load_checkpoint(ckpt_path)
    load_param_into_net(net, param_dict)
    net.set_train(False)

    data = list(dataset.create_dict_iterator(output_numpy=True, num_epochs=1))[image_id[0]]
    print("Image ID: ", image_id[0])
    img_data = data['image']
    img_metas = data['image_shape']
    gt_bboxes = data['box']
    gt_labels = data['label']
    gt_num = data['valid_num']
    gt_mask = data["mask"]

    img = mindrecord_to_rgb(img_data)

    start = time.time()
    # run net
    output = \
        net(Tensor(img_data), Tensor(img_metas), Tensor(gt_bboxes),
            Tensor(gt_labels), Tensor(gt_num), Tensor(gt_mask))
    end = time.time()
    print("Cost time of detection: {:.2f}".format(end - start))
    return output, img, img_metas


def detection(output, img, img_metas):
    """Mask RCNN Detection.
    Inputs: 
        output: evaluated results by Mask RCNN.
               [Tensor[2,80000,5],
                Tensor[2,80000,1],
                Tensor[2,80000,1]
                Tensor[2,80000,28,28]]
        img: RGB image.
        img_metas: image shape.
    """
    # scaling ratio
    ratio = img_metas[0,2]

    # output
    all_bbox = output[0][0].asnumpy()
    all_label = output[1][0].asnumpy()
    all_mask = output[2][0].asnumpy()
   
    N = 0
    id = -1
    type_ids = []
    for bool_ in all_mask:
        id += 1
        if bool_ == True and all_bbox[id,4] > 0.8:
            type_ids.append(id)
            N += 1
    print("Class Num:", N)

    # Generate random colors
    colors = random_colors(N)

    # Show area outside image boundaries.
    height = config.img_height
    width = config.img_width
    ax = get_ax(1)
    ax.set_ylim(height + 10, -10)
    ax.set_xlim(-10, width + 10)
    ax.axis('off')
    ax.set_title("Precision")

    masked_image = img.astype(np.uint32).copy()
    for j in range(N):
        color = colors[j]
        i = type_ids[j]
        # Bounding box
        x1, y1, x2, y2, zero = all_bbox[i]*ratio
        score = all_bbox[i,4]

        p = patches.Rectangle((x1, y1), x2 - x1, y2 - y1, linewidth=2,
                            alpha=0.7, linestyle="dashed",
                            edgecolor=color, facecolor='none')
        ax.add_patch(p)

        # Label
        class_names = config.data_classes
        class_id = all_label[i,0].astype(np.uint8)+1
        score = all_bbox[i,4]
        label = class_names[class_id]

        caption = "{} {:.3f}".format(label, score)
        ax.text(x1, y1 + 8, caption,
                color='w', size=11, backgroundcolor="none")

    ax.imshow(masked_image.astype(np.uint8), cmap=None)
    cv2.imwrite('out.png', masked_image.astype(np.uint8))
    cv2.imshow('1', masked_image.astype(np.uint8))


if __name__ == '__main__':
    output, img, img_metas = infer()
    detection(output, img, img_metas)
