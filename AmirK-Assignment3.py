import torch
import random
import torch.nn as nn
import os
import pandas as pd
import matplotlib.pyplot as plt
from torch.utils.data import Dataset
from PIL import Image
import numpy as np
from sklearn.model_selection import GroupKFold
from torch.autograd import Variable
from sklearn.metrics import roc_curve, auc
from itertools import cycle
import torchvision.transforms as transforms

device = 'cuda' if torch.cuda.is_available() else 'cpu'

#transform = transforms.Compose([transforms.ToTensor()])

def set_ultimate_seed(base_seed=777):
    import random
    random.seed(base_seed)

    try:
        import numpy as np
        np.random.seed(base_seed)
    except ModuleNotFoundError:
        print('Module `numpy` has not been found')
    try:
        import torch
        torch.manual_seed(base_seed + 1)
        torch.cuda.manual_seed_all(base_seed + 2)
    except ModuleNotFoundError:
        print('Module `torch` has not been found')


class OAIdataset(Dataset):
    """datasetA."""

    def __init__(self, csv_file, root_dir, transform=None):
        """
        Args:
            csv_file (string): Path to the csv file with KL grade and ID.
            root_dir (string): Directory with all the images.

        """
        self.landmarks_frame = pd.read_csv(csv_file)
        self.root_dir = root_dir
        self.transform = transform

    def __len__(self):
        return len(self.landmarks_frame)

    def __getitem__(self, idx):

        img_name = os.path.join(self.root_dir,
                                str(self.landmarks_frame['ID'].iloc[idx]))

        img_name = img_name + '.npy'
        patches, p_id = np.load(img_name)

        if self.landmarks_frame['SIDE'].iloc[idx] == 1:
            image = patches['R']
        else:
            image = patches['L']
        imageID = self.landmarks_frame.iloc[idx, 1]
        landmarks = self.landmarks_frame.iloc[idx, 3]
        if self.transform:
           image = self.transform(image)
        sample = {'image': image, 'landmarks': landmarks, 'imageID': imageID}
        return sample


batch_size = 100
Ratio = 0.2
nclass = 5
Epoch = 15
learning_rate = 0.001


class Amir(nn.Module):
    def __init__(self, nclass):
        super(Amir, self).__init__()
        self.layer1 = nn.Sequential(
            nn.Conv2d(1, 16, kernel_size=3, stride=1, padding=2),
            nn.ReLU(),
            nn.BatchNorm2d(16),
            nn.MaxPool2d(kernel_size=2, stride=2))

        self.layer2 = nn.Sequential(
            nn.Conv2d(16, 32, kernel_size=3, stride=1, padding=2),
            nn.ReLU(),
            nn.BatchNorm2d(32),
            nn.MaxPool2d(kernel_size=2, stride=2))

        self.fc = nn.Linear(9248, nclass)

    def forward(self, x):
        t = self.layer1(x)
        t = self.layer2(t)
        t = t.reshape(t.size(0), -1)
        t = self.fc(t)

        return t

model = Amir(nclass).to(device)
criterion = nn.CrossEntropyLoss()
optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)


Dataset = OAIdataset(csv_file='C:/Users/Amir Kazemtarghi/Documents/INTERNSHIP/data/IDnKL.csv',
                     root_dir='C:/Users/Amir Kazemtarghi/Documents/INTERNSHIP/data/DatabaseA/',
                     transform=None)

#  shuffling the samples but maintain both samples from same ID in train or test
z = []
odds = list(range(0, 8894, 2))
random.shuffle(odds)
for i in range(4447):
    z.append(odds[i])
    z.append(odds[i]+1)



# Splitting dataset to train and test with 4:1 ratio
Dataset_size = len(z)
split = int(np.floor(Ratio * Dataset_size))
train_indices, test_indices = z[split:], z[:split]

train_dataset = torch.utils.data.Subset(Dataset, train_indices)
test_dataset = torch.utils.data.Subset(Dataset, test_indices)

# deviding train set with Group fold for cross validation
X = train_dataset
y = Dataset.landmarks_frame.KL[train_indices]
y = y.reset_index(drop=True)
groups = Dataset.landmarks_frame.ID[train_indices]
group_kfold = GroupKFold(n_splits=5)
group_kfold.get_n_splits(X, y, groups)
print(group_kfold)

testloader = torch.utils.data.DataLoader(test_dataset,
                                         batch_size=20,
                                         num_workers=0,
                                         pin_memory=False)

for train_index, test_index in group_kfold.split(X, y, groups):
    train_subset = torch.utils.data.Subset(train_dataset, train_index)
    valid_subset = torch.utils.data.Subset(train_dataset, test_index)

    trainloader = torch.utils.data.DataLoader(train_subset,
                                              batch_size=20,
                                              num_workers=0,
                                              pin_memory=False)
    Validloader = torch.utils.data.DataLoader(valid_subset,
                                              batch_size=20,
                                              num_workers=0,
                                              pin_memory=False)

    data_loaders = {"train": trainloader, "val": Validloader}
    data_lengths = {"train": len(trainloader), "val": len(Validloader)}

    for epoch in range(Epoch):
        print('Epoch {}/{}'.format(epoch, Epoch - 1))
        print('-' * 10)

        # Each epoch has a training and validation phase
        for phase in ['train', 'val']:
            if phase == 'train':
                model.train(True)  # Set model to training mode
            else:
                model.train(False)  # Set model to evaluate mode

            running_loss = 0.0

            # Iterate over data.
            for data in data_loaders[phase]:
                optimizer.zero_grad()

                # get the input images and their corresponding labels
                images = data['image']
                key_pts = data['landmarks']
                images = images.to(device)
                key_pts = key_pts.to(device)
                # wrap them in a torch Variable
                images, key_pts = Variable(images), Variable(key_pts)
                output_pts = model(images)
                # calculate the loss between predicted and target keypoints
                loss = criterion(output_pts, key_pts)
                # zero the parameter (weight) gradients
                optimizer.zero_grad()
                # backward + optimize only if in training phase
                if phase == 'train':
                    loss.backward()
                    # update the weights
                    optimizer.step()

                # print loss statistics
                running_loss += loss.item()

            epoch_loss = running_loss / data_lengths[phase]
            print('{} Loss: {:.4f}'.format(phase, epoch_loss))


fpr = dict()
tpr = dict()
roc_auc = dict()
y = []
y_score = torch.ones(1, 5)
y_score = y_score.cpu().numpy()
n=0
model.eval()
with torch.no_grad():
    correct = 0
    total = 0
    i=0
    for data in testloader:
        images = data['image']
        key_pts = data['landmarks']
        images = images.to(device)
        key_pts = key_pts.to(device)
        outputs = model(images)
        _ , predicted = torch.max(outputs.data, 1)
        OUTPUT = outputs.cpu().numpy()
        KEY_PTS = key_pts.cpu().numpy()
        y_score = np.append(y_score, OUTPUT, axis=0)
        y = np.append(y, KEY_PTS, axis=0)
        total += key_pts.size(0)
        correct += (predicted == key_pts).sum().item()

    print('Test Accuracy of the model on the test images: {} %'.format(100 * correct / total))


# creating boolean matrix instead of one array
T1_indice = np.where(y == 0)
T2_indice = np.where(y == 1)
T3_indice = np.where(y == 2)
T4_indice = np.where(y == 3)
T5_indice = np.where(y == 4)

Y = np.zeros((len(y), 5))
Y[T1_indice, 0] = 1
Y[T2_indice, 1] = 1
Y[T3_indice, 2] = 1
Y[T4_indice, 3] = 1
Y[T5_indice, 4] = 1

# drop the fist row which is ones
y_score = np.delete(y_score, 0, axis=0)

# Computing ROC and ROC AUC
for i in range(5):
    fpr[i], tpr[i], _ = roc_curve(Y[:,i], y_score[:,i])
    roc_auc[i] = auc(fpr[i], tpr[i])


# plotting ROC
lw = 2
colors = cycle(['aqua', 'darkorange', 'cornflowerblue','red','gray'])
for i, color in zip(range(5), colors):
    plt.plot(fpr[i], tpr[i], color=color, lw=lw,
             label='ROC curve of class {0} (area = {1:0.2f})'
             ''.format(i, roc_auc[i]))

plt.plot([0, 1], [0, 1], 'k--', lw=lw)
plt.xlim([0.0, 1.0])
plt.ylim([0.0, 1.05])
plt.xlabel('False Positive Rate')
plt.ylabel('True Positive Rate')
plt.title('Some extension of Receiver operating characteristic to multi-class')
plt.legend(loc="lower right")
plt.show()










