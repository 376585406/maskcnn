# Copyright 2020-2021 Huawei Technologies Co., Ltd
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

"""Evaluation for MaskRcnn"""
import os
import time
import numpy as np

from src.utils.config import config
from src.model.mask_rcnn_r50 import MaskRcnnResnet50
# from src.model.mask_rcnn_mobilenetv1 import MaskRcnnMobilenetv1
from dataset.dataset import data_to_mindrecord_byte_image, create_coco_dataset
from src.utils.util import coco_eval, bbox2result_1image, results2json, get_seg_masks

from pycocotools.coco import COCO
from mindspore import context, Tensor
from mindspore.train.serialization import load_checkpoint, load_param_into_net
from mindspore.common import set_seed

set_seed(1)


def maskrcnn_eval(dataset_path, ckpt_path, ann_file):
    """MaskRcnn evaluation."""
    ds = create_coco_dataset(dataset_path,
                             batch_size=config.test_batch_size,
                             is_training=False)

    net = MaskRcnnResnet50(config)
    # net = MaskRcnnMobilenetv1(config)
    param_dict = load_checkpoint(ckpt_path)
    load_param_into_net(net, param_dict)
    net.set_train(False)

    eval_iter = 0
    total = ds.get_dataset_size()
    outputs = []
    dataset_coco = COCO(ann_file)

    print("\n========================================\n")
    print("total images num: ", total)
    print("Processing, please wait a moment.")
    max_num = 128
    for data in ds.create_dict_iterator(output_numpy=True, num_epochs=1):
        eval_iter = eval_iter + 1

        img_data = data['image']
        img_metas = data['image_shape']
        gt_bboxes = data['box']
        gt_labels = data['label']
        gt_num = data['valid_num']
        gt_mask = data["mask"]

        start = time.time()
        # run net
        output = \
            net(Tensor(img_data), Tensor(img_metas),
                Tensor(gt_bboxes), Tensor(gt_labels),
                Tensor(gt_num), Tensor(gt_mask))
        end = time.time()
        print("Iter {} cost time {}".format(eval_iter, end - start))

        # output
        all_bbox = output[0]
        all_label = output[1]
        all_mask = output[2]
        all_mask_fb = output[3]

        for j in range(config.test_batch_size):
            all_bbox_squee = \
                np.squeeze(all_bbox.asnumpy()[j, :, :])
            all_label_squee = \
                np.squeeze(all_label.asnumpy()[j, :, :])
            all_mask_squee = \
                np.squeeze(all_mask.asnumpy()[j, :, :])
            all_mask_fb_squee = \
                np.squeeze(all_mask_fb.asnumpy()[j, :, :, :])

            all_bboxes_tmp_mask = \
                all_bbox_squee[all_mask_squee, :]
            all_labels_tmp_mask = \
                all_label_squee[all_mask_squee]
            all_mask_fb_tmp_mask = \
                all_mask_fb_squee[all_mask_squee, :, :]

            if all_bboxes_tmp_mask.shape[0] > max_num:
                inds = np.argsort(-all_bboxes_tmp_mask[:, -1])
                inds = inds[:max_num]
                all_bboxes_tmp_mask = all_bboxes_tmp_mask[inds]
                all_labels_tmp_mask = all_labels_tmp_mask[inds]
                all_mask_fb_tmp_mask = all_mask_fb_tmp_mask[inds]

            bbox_results = \
                bbox2result_1image(all_bboxes_tmp_mask,
                                   all_labels_tmp_mask,
                                   config.num_classes)
            segm_results = \
                get_seg_masks(all_mask_fb_tmp_mask, all_bboxes_tmp_mask,
                              all_labels_tmp_mask, img_metas[j],
                              True, config.num_classes)
            outputs.append((bbox_results, segm_results))

    eval_types = ["bbox", "segm"]
    result_files = results2json(dataset_coco, outputs, "./results.pkl")
    coco_eval(result_files, eval_types, dataset_coco, single_result=False)


def eval_():
    """Execute the Evaluation."""
    context.set_context(mode=context.GRAPH_MODE)

    config.mindrecord_dir =\
        os.path.join(config.data_root,
                     config.mindrecord_dir)
    print('\neval.py config:\n', config)
    prefix = "MaskRcnn_eval.mindrecord"
    mindrecord_dir = config.mindrecord_dir
    mindrecord_file = os.path.join(mindrecord_dir, prefix)

    if not os.path.exists(mindrecord_file):
        if not os.path.isdir(mindrecord_dir):
            os.makedirs(mindrecord_dir)
        if config.dataset == "coco":
            if os.path.isdir(config.data_root):
                print("Create Mindrecord.")
                data_to_mindrecord_byte_image("coco",
                                              False,
                                              prefix,
                                              file_num=1)
                print("Create Mindrecord Done, at {}".format(mindrecord_dir))
            else:
                print("data_root not exits.")
        else:
            if os.path.isdir(config.IMAGE_DIR) and \
               os.path.exists(config.ANNO_PATH):
                print("Create Mindrecord.")
                data_to_mindrecord_byte_image("other", False,
                                              prefix, file_num=1)
                print("Create Mindrecord Done, at {}".format(mindrecord_dir))
            else:
                print("IMAGE_DIR or ANNO_PATH not exits.")

    print("Start Eval!")
    maskrcnn_eval(mindrecord_file, config.checkpoint_path, config.ann_file)
    print("ckpt_path=", config.checkpoint_path)


if __name__ == '__main__':
    eval_()
