from PIL import Image
import numpy as np
import os

img_dir = os.path.expanduser('~/data/tiger/tissue-cells/images')
mask_dir = os.path.expanduser('~/data/tiger/tissue-cells/masks')

f = os.listdir(img_dir)[0]
img = Image.open(os.path.join(img_dir, f))
print('image:', f, img.size, img.mode)

mf = os.listdir(mask_dir)[0]
mask = np.array(Image.open(os.path.join(mask_dir, mf)))
print('mask:', mf, mask.shape, mask.dtype, 'unique values:', np.unique(mask))
