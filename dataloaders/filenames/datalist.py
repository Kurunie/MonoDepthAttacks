import os
import random


def prt_datalist(mode):
    cwdpath = os.getcwd()
    datapath = os.path.join(cwdpath, "data", "kitti")
    if mode == "test":
        path = os.path.join(cwdpath, "dataloaders", "filenames")
        f = open(os.path.join(path, "eigen_test_files.txt"), "w+")
        l1 = os.path.join(datapath, "val")
        l2 = os.listdir(l1) # 数据集名称目录
        for ll2 in l2:
            l3 = os.path.join(l1, ll2)
            # image_02/data, image_03/data, proj_depth/groundtruth/image_02//03
            li2 = os.path.join(l3, "proj_depth", "groundtruth", "image_02")
            lli2 = os.listdir(li2)
            num = len(lli2)
            T = 40 # 每个数据集采样个数
            L = range(0, num)
            b = random.sample(L, min(T, num))
            for a in b:
                af = lli2[a]
                a1 = os.path.join("val", ll2, "image_02", "data", af)
                a2 = os.path.join("val", ll2, "image_03", "data", af)
                a3 = os.path.join("val", ll2, "proj_depth", "groundtruth", "image_02", af)
                a4 = os.path.join("val", ll2, "proj_depth", "groundtruth", "image_03", af)

                f.write("%s %s %s %s\n" %(a1, a2, a3, a4))

        f.close()
    if mode == "train":
        path = os.path.join(cwdpath, "dataloaders", "filenames")
        f = open(os.path.join(path, "eigen_train_files.txt"), "w+")
        l1 = os.path.join(datapath, "train")
        l2 = os.listdir(l1) # 数据集名称目录
        for ll2 in l2:
            l3 = os.path.join(l1, ll2)
            # image_02/data, image_03/data, proj_depth/groundtruth/image_02//03
            li2 = os.path.join(l3, "image_02", "data")
            lli2 = os.listdir(li2)
            num = len(lli2)
            T = 40  # 每个数据集采样个数
            L = range(0, num)
            b = random.sample(L, min(T, num))
            for a in b:
                af = lli2[a]
                a1 = os.path.join("train", ll2, "image_02", "data", af)
                a2 = os.path.join("train", ll2, "image_03", "data", af)
                a3 = os.path.join("train", ll2, "proj_depth", "groundtruth", "image_02", af)
                a4 = os.path.join("train", ll2, "proj_depth", "groundtruth", "image_03", af)

                f.write("%s %s %s %s\n" % (a1, a2, a3, a4))
        f.close()
prt_datalist("test")
prt_datalist("train")