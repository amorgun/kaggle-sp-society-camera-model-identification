# coding: utf-8
__author__ = 'ZFTurbo: https://kaggle.com/zfturbo'

from a00_common_functions import *
import jpeg4py as jpeg
from io import BytesIO
from PIL import Image
import math
import pyvips
from keras.utils import to_categorical
from keras.applications import *


MANIPULATIONS = ['jpg70', 'jpg90', 'gamma0.8', 'gamma1.2', 'bicubic0.5', 'bicubic0.8', 'bicubic1.5', 'bicubic2.0']


def get_crop(img, crop_size, random_crop=False):
    center_x, center_y = img.shape[1] // 2, img.shape[0] // 2
    half_crop = crop_size // 2
    pad_x = max(0, crop_size - img.shape[1])
    pad_y = max(0, crop_size - img.shape[0])
    if (pad_x > 0) or (pad_y > 0):
        img = np.pad(img, ((pad_y//2, pad_y - pad_y//2), (pad_x//2, pad_x - pad_x//2), (0,0)), mode='wrap')
        center_x, center_y = img.shape[1] // 2, img.shape[0] // 2
    if random_crop:
        freedom_x, freedom_y = img.shape[1] - crop_size, img.shape[0] - crop_size
        if freedom_x > 0:
            center_x += np.random.randint(math.ceil(-freedom_x/2), freedom_x - math.floor(freedom_x/2) )
        if freedom_y > 0:
            center_y += np.random.randint(math.ceil(-freedom_y/2), freedom_y - math.floor(freedom_y/2) )

    return img[center_y - half_crop : center_y + crop_size - half_crop, center_x - half_crop : center_x + crop_size - half_crop]


def random_manipulation(img, manipulation=None):
    global MANIPULATIONS

    if manipulation is None:
        manipulation = random.choice(MANIPULATIONS)

    if manipulation.startswith('jpg'):
        quality = int(manipulation[3:])
        out = BytesIO()
        im = Image.fromarray(img)
        im.save(out, format='jpeg', quality=quality)
        im_decoded = jpeg.JPEG(np.frombuffer(out.getvalue(), dtype=np.uint8)).decode()
        del out
        del im
    elif manipulation.startswith('gamma'):
        gamma = float(manipulation[5:])
        # alternatively use skimage.exposure.adjust_gamma
        # img = skimage.exposure.adjust_gamma(img, gamma)
        im_decoded = np.uint8(cv2.pow(img / 255., gamma)*255.)
    elif manipulation.startswith('bicubic'):
        scale = float(manipulation[7:])
        im_decoded = cv2.resize(img,(0,0), fx=scale, fy=scale, interpolation = cv2.INTER_CUBIC)
    else:
        assert False
    return im_decoded


def preprocess_image(img, classifier='ResNet50'):
    kernel_filter = False
    if kernel_filter:
        # see slide 13
        # http://www.lirmm.fr/~chaumont/publications/WIFS-2016_TUAMA_COMBY_CHAUMONT_Camera_Model_Identification_With_CNN_slides.pdf
        kernel_filter = 1 / 12. * np.array([ \
            [-1, 2, -2, 2, -1], \
            [2, -6, 8, -6, 2], \
            [-2, 8, -12, 8, -2], \
            [2, -6, 8, -6, 2], \
            [-1, 2, -2, 2, -1]])

        return cv2.filter2D(img.astype(np.float32), -1, kernel_filter)
        # kernel filter already puts mean ~0 and roughly scales between [-1..1]
        # no need to preprocess_input further
    else:
        # find `preprocess_input` function specific to the classifier
        classifier_to_module = {
            'NASNetLarge': 'nasnet',
            'NASNetMobile': 'nasnet',
            'DenseNet40': 'densenet',
            'DenseNet121': 'densenet',
            'DenseNet161': 'densenet',
            'DenseNet201': 'densenet',
            'InceptionResNetV2': 'inception_resnet_v2',
            'InceptionV3': 'inception_v3',
            'MobileNet': 'mobilenet',
            'ResNet50': 'resnet50',
            'VGG16': 'vgg16',
            'VGG19': 'vgg19',
            'Xception': 'xception',

        }

        if classifier in classifier_to_module:
            classifier_module_name = classifier_to_module[classifier]
        else:
            classifier_module_name = 'xception'

        preprocess_input_function = getattr(globals()[classifier_module_name], 'preprocess_input')
        return preprocess_input_function(img.astype(np.float32))


def process_item(item, training, transforms=[[]], crop_size=512, classifier='ResNet50'):
    verbose = False
    class_name = os.path.basename(os.path.dirname(item))
    class_idx = get_class(class_name)

    validation = not training

    if 0:
        jpg_item = jpeg.JPEG(item)
        print(item, jpg_item)
        img = jpg_item.decode()
    elif 0:
        img = cv2.imread(item)
        img = np.transpose(img, (1, 0, 2))
        img = np.flip(img, axis=0)
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    elif 0:
        img = Image.open(item)
        img = np.array(img)

    img = pyvips.Image.new_from_file(item, access='sequential')
    img = np.ndarray(buffer=img.write_to_memory(),
                   dtype=np.uint8,
                   shape=[img.height, img.width, img.bands])

    shape = list(img.shape[:2])

    if 0:
        # discard images that do not have right resolution
        if shape not in RESOLUTIONS[class_idx]:
            return None

        # some images may not be downloaded correctly and are B/W, discard those
        if img.ndim != 3:
            return None

    if len(transforms) == 1:
        _img = img
    else:
        _img = np.copy(img)

        img_s         = [ ]
        manipulated_s = [ ]
        class_idx_s   = [ ]

    for transform in transforms:

        force_manipulation = 'manipulation' in transform

        if ('orientation' in transform) and (ORIENTATION_FLIP_ALLOWED[class_idx] is False):
            continue

        force_orientation  = ('orientation'  in transform) and ORIENTATION_FLIP_ALLOWED[class_idx]

        # some images are landscape, others are portrait, so augment training by randomly changing orientation
        if ((np.random.rand() < 0.5) and training and ORIENTATION_FLIP_ALLOWED[class_idx]) or force_orientation:
            img = np.rot90(_img, 1, (0,1))
            # is it rot90(..3..), rot90(..1..) or both?
            # for phones with landscape mode pics could be taken upside down too, although less likely
            # most of the test images that are flipped are 1
            # however,eg. img_4d7be4c_unalt looks 3
            # and img_4df3673_manip img_6a31fd7_unalt looks 2!
        else:
            img = _img

        img = get_crop(img, crop_size * 2, random_crop=True if training else False)
        # * 2 bc may need to scale by 0.5x and still get a 512px crop

        if verbose:
            print("om: ", img.shape, item)

        manipulated = 0.
        if ((np.random.rand() < 0.5) and training) or force_manipulation:
            img = random_manipulation(img)
            manipulated = 1.
            if verbose:
                print("am: ", img.shape, item)

        img = get_crop(img, crop_size, random_crop=True if training else False)
        if verbose:
            print("ac: ", img.shape, item)

        img = preprocess_image(img, classifier)
        if verbose:
            print("ap: ", img.shape, item)

        if len(transforms) > 1:
            img_s.append(img)
            manipulated_s.append(manipulated)
            class_idx_s.append(class_idx)

    if len(transforms) == 1:
        return img, manipulated, class_idx
    else:
        return img_s, manipulated_s, class_idx_s
