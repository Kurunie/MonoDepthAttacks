__author__ = 'danielzgsilva', 'kesaroid'

from datetime import datetime
import shutil
import socket
import time
import os
os.environ["CUDA_VISIBLE_DEVICES"] = "0"
import torch
from torchvision.utils import save_image
import torch.nn as nn
import torch.nn.functional as F
from torch.optim import lr_scheduler

from network import FCRN
from utils import criteria, utils
from utils.metrics import AverageMeter, Result

from AdaBins.models import UnetAdaptiveBins
from AdaBins import model_io

from DPT.dpt.models import DPTDepthModel
from DPT.dpt.models import DPTSegmentationModel

from attacks.MIFGSM import MIFGSM
from attacks.pgd import PGD


def main():
    global args, best_result, output_directory
    print(torch.__version__)

    # set random seed
    torch.manual_seed(args.manual_seed)

    # Use GPU if available

    if torch.cuda.device_count() > 1:
        print("Let's use", torch.cuda.device_count(), "GPUs!")

        # args.batch_size = args.batch_size * torch.cuda.device_count()
    else:
        print("Let's use GPU ", torch.cuda.current_device())

    # print("Let's use GPU ", torch.cuda.current_device())
    # Validation dataloader
    _, val_loader = utils.create_loader(args)
    del _

    segm_model = None

    if args.resume is not None:
        assert os.path.isfile(args.resume), \
            "=> no checkpoint found at '{}'".format(args.resume)
        print("=> loading checkpoint '{}'".format(args.resume))

    # Choose the model to be loaded
    if args.model == 'resnet':
        checkpoint = torch.load(args.resume)

        start_epoch = checkpoint['epoch'] + 1
        best_result = checkpoint['best_result']
        optimizer = checkpoint['optimizer']

        # solve 'out of memory'
        model = checkpoint['model']

        print("=> loaded checkpoint (epoch {})".format(checkpoint['epoch']))

        # clear memory
        del checkpoint

    # Adabins model
    elif args.model == "adabins":
        MIN_DEPTH = 1e-3
        MAX_DEPTH_NYU = 10
        MAX_DEPTH_KITTI = 80
        N_BINS = 256

        # Load model w.r.t dataset
        if args.dataset == 'kitti':
            model = UnetAdaptiveBins.build(
                n_bins=N_BINS, min_val=MIN_DEPTH, max_val=MAX_DEPTH_KITTI)
        elif args.dataset == 'saved_images':
            model = UnetAdaptiveBins.build(
                n_bins=N_BINS, min_val=MIN_DEPTH, max_val=MAX_DEPTH_KITTI)
        elif args.dataset == 'nyu':
            model = UnetAdaptiveBins.build(
                n_bins=N_BINS, min_val=MIN_DEPTH, max_val=MAX_DEPTH_NYU)
        else:
            assert (False, "{} dataset not supported".format(args.dataset))

        model, _, _ = model_io.load_checkpoint(args.resume, model)

    # DPT-hybrid model
    elif args.model == "dpt":
        attention_hooks = True

        if args.dataset == 'kitti':
            scale = 0.00006016
            shift = 0.00579
        elif args.dataset == 'saved_images':
            scale = 0.00006016
            shift = 0.00579
        elif args.dataset == 'nyu':
            scale = 0.000305
            shift = 0.1378

        model = DPTDepthModel(
            path=args.resume,
            scale=scale,
            shift=shift,
            invert=True,
            backbone="vitb_rn50_384",
            non_negative=True,
            enable_attention_hooks=attention_hooks,
        )
        
        # Targeted attack: Load Segmentation model
        if args.targeted:
            segm_model = DPTSegmentationModel(
                150,
                path='DPT/weights/dpt_hybrid-ade20k-53898607.pt',
                backbone="vitb_rn50_384",
            )

        print('model {} loaded'.format(args.resume))
    else:
        assert(False, "{} model not supported".format(args.model))

    torch.cuda.empty_cache()
    model = model.cuda()

    # Choose attackers
    attacker = None
    if args.attack == 'mifgsm':
        print('attacking with {}'.format(args.attack))
        attacker = MIFGSM(model, "cuda:0", args.loss,
                          eps=mifgsm_params['eps'],
                          steps=mifgsm_params['steps'],
                          decay=mifgsm_params['decay'],
                          alpha=mifgsm_params['alpha'],
                          TI=mifgsm_params['TI'],
                          k_=mifgsm_params['k'],
                          targeted=args.targeted,
                          test=args.model)
    elif args.attack == 'pgd':
        print('attacking with {}'.format(args.attack))
        attacker = PGD(model, "cuda:0", args.loss,
                       norm=pgd_params['norm'],
                       eps=pgd_params['eps'],
                       alpha=pgd_params['alpha'],
                       iters=pgd_params['iterations'],
                       TI=pgd_params['TI'],
                       k_=mifgsm_params['k'],
                       test=args.model)
    else:
        print('no attack')

    # create directory path
    if args.eval_output_dir is not None:
        output_directory = args.eval_output_dir
    else:
        output_directory = os.path.join(os.path.dirname(
            os.path.abspath(__file__)), 'eval_results')

    if not os.path.exists(output_directory):
        os.makedirs(output_directory)

    # Save evaluation results
    eval_txt = os.path.join(output_directory, 'eval_results_{}_{}_{}.txt'.format(
        args.model, args.dataset, args.attack))

    # make dirs to save imgs unless we're testing on already saved imgs
    if args.save_image_dir is not None and args.dataset != 'saved_images':
        img_dir = os.path.join(args.save_image_dir, 'imgs')
        gt_dir = os.path.join(args.save_image_dir, 'gt')

        if not os.path.exists(img_dir):
            os.makedirs(img_dir)
        if not os.path.exists(gt_dir):
            os.makedirs(gt_dir)

    # evaluate on validation set
    result, img_merge = validate(
        val_loader, model, segm_model, attacker, args.save_image_dir, args.num_images_to_save)

    with open(eval_txt, 'w') as txtfile:
        txtfile.write(
            "rmse={:.3f}, rml={:.3f}, log10={:.3f}, d1={:.3f}, d2={:.3f}, dd31={:.3f}, t_gpu={:.4f}".
            format(result.rmse, result.absrel, result.lg10, result.delta1, result.delta2,
                   result.delta3, result.gpu_time))

    if img_merge is not None:
        img_filename = output_directory + '/eval_results_{}_{}_{}_{}_{}.png'.format(
            args.model, args.dataset, args.attack, args.targeted, args.move_target)
        utils.save_image(img_merge, img_filename)


# validation
def validate(val_loader, model, segm_model=None, attacker=None, save_img_dir=None, num_imgs_to_save=None):
    average_meter = AverageMeter()

    model.eval()  # switch to evaluate mode
    targeted_metrics = {'rmse': [], 'absrel': [], 'log10': []}

    end = time.time()

    skip = len(val_loader) // 9  # save images every skip iters

    for i, (input, target) in enumerate(val_loader):
        input, target = input.cuda(), target.cuda()

        # Get Adversary function
        adv_input, segm = get_adversary(input, target, segm_model, attacker)

        torch.cuda.synchronize()
        data_time = time.time() - end

        # compute output
        end = time.time()
        with torch.no_grad():
            if args.model == 'adabins':
                _, pred = model(adv_input)
            else:
                pred = model(adv_input)

        # Post-processing for few of the models
        pred = post_process(pred)

        torch.cuda.synchronize()
        gpu_time = time.time() - end

        # measure accuracy and record loss
        result = Result()
        result.evaluate(pred.data, target.data)
        if args.targeted:
            rmse, absrel, log10 = result.targeted_eval(
                pred.data.squeeze(1), target.data.squeeze(1), segm)
            if rmse != float('nan'):
                targeted_metrics['rmse'].append(rmse)
            if absrel != float('nan'):
                targeted_metrics['absrel'].append(absrel)
            if log10 != float('nan'):
                targeted_metrics['log10'].append(log10)

        average_meter.update(result, gpu_time, data_time, input.size(0))
        end = time.time()

        # save 8 images for visualization
        if args.dataset == 'kitti':
            rgb = adv_input[0]
            target = target[0]
            pred = pred[0]
        else:
            rgb = input

        if i == 0:
            img_merge = utils.merge_into_row(rgb, target, pred)
        elif (i < 8 * skip) and (i % skip == 0):
            row = utils.merge_into_row(rgb, target, pred)
            img_merge = utils.add_row(img_merge, row)

        if (i + 1) % args.print_freq == 0:
            print('Test: [{0}/{1}]\t'
                  't_GPU={gpu_time:.3f}({average.gpu_time:.3f})\n\t'
                  'RMSE={result.rmse:.2f}({average.rmse:.2f}) '
                  'RML={result.absrel:.2f}({average.absrel:.2f}) '
                  'Log10={result.lg10:.3f}({average.lg10:.3f}) '
                  'Delta1={result.delta1:.3f}({average.delta1:.3f}) '
                  'Delta2={result.delta2:.3f}({average.delta2:.3f}) '
                  'Delta3={result.delta3:.3f}({average.delta3:.3f})'.format(
                      i + 1, len(val_loader), gpu_time=gpu_time, result=result, average=average_meter.average()))

        # save images only if we're not testing on already saved images
        if save_img_dir is not None and args.dataset != 'saved_images':
            img = adv_input[0]
            depth = target[0]
            save_image(img, os.path.join(
                save_img_dir, 'imgs', '{}.png'.format(i)))
            save_image(depth, os.path.join(
                save_img_dir, 'gt', '{}.png'.format(i)))

        if save_img_dir is not None and i > num_imgs_to_save:
            break

    avg = average_meter.average()

    if args.targeted:
        avg_rmse = sum(targeted_metrics['rmse']) / \
            len(targeted_metrics['rmse'])
        avg_absrel = sum(targeted_metrics['absrel']) / \
            len(targeted_metrics['absrel'])
        avg_log10 = sum(targeted_metrics['log10']) / \
            len(targeted_metrics['log10'])

        print('\n*\n'
              'RMSE={}\n'
              'Rel={}\n'
              'Log10={}\n'.format(avg_rmse, avg_absrel, avg_log10))

    print('\n*\n'
          'RMSE={average.rmse:.3f}\n'
          'Rel={average.absrel:.3f}\n'
          'Log10={average.lg10:.3f}\n'
          'Delta1={average.delta1:.3f}\n'
          'Delta2={average.delta2:.3f}\n'
          'Delta3={average.delta3:.3f}\n'
          't_GPU={time:.3f}\n'.format(
              average=avg, time=avg.gpu_time))

    return avg, img_merge


def get_adversary(data, target, segm_model=None, attacker=None):
    if attacker is not None:
        if args.targeted:
            segm_model.eval()
            # Get Segmentation results
            out = segm_model.forward(data.cpu())
            segm = torch.argmax(out, dim=1) + 1
            # Find Depth target using M and alpha for a target class
            adv_target = torch.where(
                segm == targeted_class, target.cpu() * (1 + args.move_target), target.cpu())

        else:
            adv_target = target
            segm = None
        # Attack object: outputs perturbated image
        pert_image = attacker(data.cuda(), adv_target.cuda())
    else:
        pert_image = data
        segm = None

    return pert_image, segm


def post_process(depth,):
    if args.model == 'adabins':
        # upscale adabins output to original size
        if args.dataset == 'kitti':
            depth = F.interpolate(depth, size=(228, 912), mode='bilinear')
        elif args.dataset == 'saved_images':
            depth = F.interpolate(depth, size=(228, 912), mode='bilinear')
        elif args.dataset == 'nyu':
            depth = F.interpolate(depth, size=(480, 640), mode='bilinear')

    elif args.model == 'dpt':
        depth = depth.unsqueeze(1)

    else:
        pass

    return depth


if __name__ == '__main__':
    # Target class for the KITTI dataset for Targeted attacks
    targeted_class = 26  # cars

    args = utils.parse_command()
    print(args)
    if args.targeted:
        print('Targeted_class: {} --- Moved by {}'.format(targeted_class, args.move_target))
    
    # PGD and MIFGSM parameters from arguments
    mifgsm_params = {'eps': args.epsilon, 'steps': args.iterations,
                     'decay': 1.0, 'alpha': args.alpha, 'TI': args.g_smooth, 'k': args.k}
    pgd_params = {'norm': 'inf', 'eps': args.epsilon, 'alpha': args.alpha,
                  'iterations': args.iterations, 'TI': args.g_smooth, 'k': args.k}

    best_result = Result()
    best_result.set_to_worst()

    main()
