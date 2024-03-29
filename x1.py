# # -*- coding: utf-8 -*-
# """x1.ipynb

# Automatically generated by Colaboratory.

# Original file is located at
#     https://colab.research.google.com/drive/1QYgI-GoXIEpRvF6o0JQ7mx-xW4k5ncLu
# """

# # memory footprint support libraries/code
# !ln -sf /opt/bin/nvidia-smi /usr/bin/nvidia-smi
# !pip install gputil
# !pip install psutil
# !pip install humanize

# import psutil
# import humanize
# import os
# import GPUtil as GPU

# GPUs = GPU.getGPUs()
# # XXX: only one GPU on Colab and isn’t guaranteed
# gpu = GPUs[0]
# def printm():
#     process = psutil.Process(os.getpid())
#     print("Gen RAM Free: " + humanize.naturalsize(psutil.virtual_memory().available), " |     Proc size: " + humanize.naturalsize(process.memory_info().rss))
#     print("GPU RAM Free: {0:.0f}MB | Used: {1:.0f}MB | Util {2:3.0f}% | Total     {3:.0f}MB".format(gpu.memoryFree, gpu.memoryUsed, gpu.memoryUtil*100, gpu.memoryTotal))
# printm()

import os
import torch
import torch.nn as n
import torch.nn.functional as f
import numpy as np
#from torchsummary import summary
import torch.optim as optim
from torchvision import models, datasets
from torchvision.transforms import transforms
from torch.utils.data import Dataset, DataLoader
from PIL import Image
from matplotlib import pyplot as plt
#from tqdm import tqdm_notebook,tqdm
import cv2
import torchvision.utils as vutils

import warnings
warnings.filterwarnings('ignore')

device = torch.device("cuda" )

def downloadSampling(img):
    image = np.array(img)
    image_blur = cv2.resize(image,(64,64),cv2.INTER_CUBIC)
    new_image = Image.fromarray(image_blur)
    return new_image

HR_transform = transforms.Compose([
                                 transforms.Resize((256,256)),
                                 transforms.ToTensor(),
                                 transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5))
                                ])

LR_transform = transforms.Compose([
                                   transforms.Resize((64,64)),
                                   transforms.Lambda(downloadSampling),
                                   transforms.ToTensor(),
                                   transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5))
                                ])

# LR_train_dataset = datasets.CelebA(root = "celebA",transform = LR_transform, download = True)
LR_train_dataset = datasets.ImageFolder(root = "/workspace/storage/model/train",transform = LR_transform)
print(LR_train_dataset)
LR_train_dataloader = DataLoader(LR_train_dataset, batch_size = 16, num_workers = 0)

# HR_train_dataset = datasets.CelebA(root = "celebA",transform = HR_transform, download = False)
HR_train_dataset = datasets.ImageFolder(root = "/workspace/storage/model/train",transform = HR_transform)

HR_train_dataloader = DataLoader(HR_train_dataset, batch_size = 16, num_workers = 0 )

HR_batch = next(iter(HR_train_dataloader))
plt.figure(figsize=(20,20))
plt.axis("off")
plt.title("Training Images")
plt.imshow(np.transpose(vutils.make_grid(HR_batch[0].to(device)[:8], padding=2, normalize=True).cpu(),(1,2,0)))

LR_batch = next(iter(LR_train_dataloader))
plt.figure(figsize=(20,20))
plt.axis("off")
plt.title("Training Images")
plt.imshow(np.transpose(vutils.make_grid(LR_batch[0].to(device)[:8], padding=2, normalize=True).cpu(),(1,2,0)))

vgg = models.vgg19(pretrained=True).to(device)

class ResidualDenseBlock(n.Module):
    def __init__(self,in_channel = 64,inc_channel = 32, beta = 0.2):
        super().__init__()
        self.conv1 = n.Conv2d(in_channel, inc_channel, 3, 1, 1)
        self.conv2 = n.Conv2d(in_channel + inc_channel, inc_channel, 3, 1, 1)
        self.conv3 = n.Conv2d(in_channel + 2 * inc_channel, inc_channel, 3, 1, 1)
        self.conv4 = n.Conv2d(in_channel + 3 * inc_channel, inc_channel, 3, 1, 1)
        self.conv5 = n.Conv2d(in_channel + 4 * inc_channel,  in_channel, 3, 1, 1)
        self.lrelu = n.LeakyReLU()
        self.b = beta
        
    def forward(self, x):
        block1 = self.lrelu(self.conv1(x))
        block2 = self.lrelu(self.conv2(torch.cat((block1, x), dim = 1)))
        block3 = self.lrelu(self.conv3(torch.cat((block2, block1, x), dim = 1)))
        block4 = self.lrelu(self.conv4(torch.cat((block3, block2, block1, x), dim = 1)))
        out = self.conv5(torch.cat((block4, block3, block2, block1, x), dim = 1))
        
        return x + self.b * out

class ResidualInResidualDenseBlock(n.Module):
    def __init__(self, in_channel = 64, out_channel = 32, beta = 0.2):
        super().__init__()
        self.RDB = ResidualDenseBlock(in_channel, out_channel)
        self.b = beta
    
    def forward(self, x):
        out = self.RDB(x)
        out = self.RDB(out)
        out = self.RDB(out)
        
        return x + self.b * out

class Generator(n.Module):
    def __init__(self,in_channel = 3, out_channel = 3, noRRDBBlock = 23):
        super().__init__()   
        self.conv1 = n.Conv2d(3, 64, 3, 1, 1)

        RRDB = ResidualInResidualDenseBlock()
        RRDB_layer = []
        for i in range(noRRDBBlock):
            RRDB_layer.append(RRDB)
        self.RRDB_block =  n.Sequential(*RRDB_layer)

        self.RRDB_conv2 = n.Conv2d(64, 64, 3, 1, 1)
        self.upconv = n.Conv2d(64, 64, 3, 1, 1)

        self.out_conv = n.Conv2d(64, 3, 3, 1, 1)
    
    def forward(self, x):
        first_conv = self.conv1(x)
        RRDB_full_block = torch.add(self.RRDB_conv2(self.RRDB_block(first_conv)),first_conv)
        upconv_block1 = self.upconv(f.interpolate(RRDB_full_block, scale_factor = 2))
        upconv_block2 = self.upconv(f.interpolate(upconv_block1, scale_factor = 2))
        out = self.out_conv(upconv_block2)
        
        return out

gen = Generator().to(device)
# summary(gen,(3,64,64))

class Discriminator(n.Module):
    def __init__(self):
        super().__init__()
        self.conv1 = n.Conv2d(3,64,3,padding=1,bias=False)
        self.conv2 = n.Conv2d(64,64,3,stride=2,padding=1,bias=False)
        self.bn2 = n.BatchNorm2d(64)
        self.conv3 = n.Conv2d(64,128,3,padding=1,bias=False)
        self.bn3 = n.BatchNorm2d(128)
        self.conv4 = n.Conv2d(128,128,3,stride=2,padding=1,bias=False)
        self.bn4 = n.BatchNorm2d(128)
        self.conv5 = n.Conv2d(128,256,3,padding=1,bias=False)
        self.bn5 = n.BatchNorm2d(256)
        self.conv6 = n.Conv2d(256,256,3,stride=2,padding=1,bias=False)
        self.bn6 = n.BatchNorm2d(256)
        self.conv7 = n.Conv2d(256,512,3,padding=1,bias=False)
        self.bn7 = n.BatchNorm2d(512)
        self.conv8 = n.Conv2d(512,512,3,stride=2,padding=1,bias=False)
        self.bn8 = n.BatchNorm2d(512)
        self.fc1 = n.Linear(512*16*16,1024)
        self.fc2 = n.Linear(1024,1)
        self.drop = n.Dropout2d(0.3)
        
    def forward(self,x):
        block1 = f.leaky_relu(self.conv1(x))
        block2 = f.leaky_relu(self.bn2(self.conv2(block1)))
        block3 = f.leaky_relu(self.bn3(self.conv3(block2)))
        block4 = f.leaky_relu(self.bn4(self.conv4(block3)))
        block5 = f.leaky_relu(self.bn5(self.conv5(block4)))
        block6 = f.leaky_relu(self.bn6(self.conv6(block5)))
        block7 = f.leaky_relu(self.bn7(self.conv7(block6)))
        block8 = f.leaky_relu(self.bn8(self.conv8(block7)))
        block8 = block8.view(-1,block8.size(1)*block8.size(2)*block8.size(3))
        block9 = f.leaky_relu(self.fc1(block8))
#         block9 = block9.view(-1,block9.size(1)*block9.size(2)*block9.size(3))
        block10 = torch.sigmoid(self.drop(self.fc2(block9)))
        return block9

disc = Discriminator().to(device)

gen_optimizer = optim.Adam(gen.parameters(),lr=0.0002)
disc_optimizer = optim.Adam(disc.parameters(),lr=0.0002)

class Losses():
    def __init__(self):
        super().__init__()
        self.disc_losss = n.BCEWithLogitsLoss()
        self.gen_losss = n.BCEWithLogitsLoss()
        self.vgg_loss = n.MSELoss()
        self.mse_loss = n.MSELoss()
        self.lamda = 0.005
        self.eeta = 0.02 
        
    def calculateLoss(self,discriminator, generator,LR_image, HR_image):

        disc_optimizer.zero_grad()
        generated_output = generator(LR_image.to(device).float())
        fake_data = generated_output.clone()
        fake_label = discriminator(fake_data)

        
        HR_image_tensor = HR_image.to(device).float()
        real_data = HR_image_tensor.clone()
        real_label = discriminator(real_data)
        
        relativistic_d1_loss = self.disc_losss((real_label - torch.mean(fake_label)), torch.ones_like(real_label, dtype = torch.float))
        relativistic_d2_loss = self.disc_losss((fake_label - torch.mean(real_label)), torch.zeros_like(fake_label, dtype = torch.float))      

        d_loss = (relativistic_d1_loss + relativistic_d2_loss) / 2
        d_loss.backward(retain_graph = True)
        disc_optimizer.step()

        fake_label_ = discriminator(generated_output)
        real_label_ = discriminator(real_data)
        gen_optimizer.zero_grad()

        g_real_loss = self.gen_losss((fake_label_ - torch.mean(real_label_)), torch.ones_like(fake_label_, dtype = torch.float))
        g_fake_loss = self.gen_losss((real_label_ - torch.mean(fake_label_)), torch.zeros_like(fake_label_, dtype = torch.float))
        g_loss = (g_real_loss + g_fake_loss) / 2
        
        v_loss = self.vgg_loss(vgg.features[:6](generated_output),vgg.features[:6](real_data))
        m_loss = self.mse_loss(generated_output,real_data)
        generator_loss = self.lamda * g_loss + v_loss + self.eeta * m_loss
        generator_loss.backward()
        gen_optimizer.step()

        return d_loss,generator_loss

def loadImages(imageList,path):
    images=[]
    for image in (imageList):
        img = cv2.imread(os.path.join(path,image))
        img = np.moveaxis(img, 2, 0)
#         print(img.shape)
        images.append(img)
    return np.array(images)

epochs = 1000

weight_file = "/workspace/storage/model/ESRPT_weights"
out_path = "/workspace/storage/model/out"

if not os.path.exists(weight_file):
    os.makedirs(weight_file)

if not os.path.exists(out_path):
    os.makedirs(out_path)

test_image_path = os.path.join(os.getcwd(),"/workspace/storage/model/Val_data")

images = os.listdir(test_image_path)

def load_checkpoint(filepath):
    checkpoint = torch.load(filepath)
    model = checkpoint['model']
    model.load_state_dict(checkpoint['state_dict'])
    for parameter in model.parameters():
        parameter.requires_grad = False
    
    model.eval()
    
    return model

def imagePostProcess(imagedir,modelPath):
    imagelist=[]
#     images = os.listdir(imagedir)
    for img in imagedir:
        img = cv2.resize(cv2.GaussianBlur(cv2.imread(os.path.join(test_image_path,img)),(5,5),cv2.BORDER_DEFAULT),(64,64)) 
        imagelist.append(img)
    imagearray = np.array(imagelist)/255
    
    imagearrayPT = np.moveaxis(imagearray,3,1)

    model = load_checkpoint(modelPath)
    im_tensor = torch.from_numpy(imagearrayPT).float()
    out_tensor = model(im_tensor)
    out = out_tensor.numpy()
    out = np.moveaxis(out,1,3)
    out = np.clip(out,0,1)
    
    return out


for epoch in (range(epochs)):
    dloss_list=[]
    gloss_list=[]
    
    for data_idx ,(HR_data, LR_data) in enumerate(zip(HR_train_dataloader,LR_train_dataloader)):
        HR_data, LR_data = HR_data[0], LR_data[0]
        
        
        disc_loss, gen_loss = Losses().calculateLoss(disc, gen, LR_data, HR_data)
        dloss_list.append(disc_loss.item())
        gloss_list.append(gen_loss.item())
        # print(disc_loss, gen_loss)
        torch.cuda.empty_cache()
#         if(data_idx == 125):
#             break

    print("Epoch ::::  "+str(epoch+1)+"  d_loss ::: "+str(np.mean(dloss_list))+"  g_loss :::"+str(np.mean(gloss_list)))

    if(((epoch+1)%10)==0):
    
        checkpoint = {'model': Generator(),
                'input_size': 64,
                'output_size': 256,
                'state_dict': gen.state_dict()}
        torch.save(checkpoint,os.path.join(weight_file,"ESR_"+str(epoch+1)+".pth"))

out_images = imagePostProcess(images,os.path.join(weight_file,"ESR_1000"+".pth"))
for i  in range(len(out_images)):
    # print(img)
    plt.imshow(out_images[i])
    plt.axis('off')
    plt.savefig(os.path.join(os.getcwd(),"/workspace/storage/model/out/")+str(images[i]), bbox_inches='tight', pad_inches=0)
