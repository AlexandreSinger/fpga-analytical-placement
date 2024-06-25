# Run this script in google colab to plot hpwl
import matplotlib.pyplot as plt
import csv

file = open("/content/hpwls.csv", "r")
reader = csv.reader(file)
file_list = []

for row in reader:
  file_list.append(row)
i = 0
HPWL = []
PLHPWL = []
title = ""
while i < len(file_list):
  if i % 3 == 0:
    title = file_list[i][0] + " " + file_list[i][1]
  if i%3 == 1:
    HPWL=[float(e) for e in file_list[i]]
  if i%3 == 2:
    PLHPWL=[float(e) for e in file_list[i]]
    min_len = min(len(HPWL), len(PLHPWL))
    HPWL = HPWL[:min_len]
    PLHPWL = PLHPWL[:min_len]
    x_values = range(min_len)
    print(HPWL)
    print(PLHPWL)
    # Create a plot
    plt.plot(x_values, HPWL, label='HPWL', marker='o')
    plt.plot(x_values, PLHPWL, label='Post Legalized HPWL', marker='x')

    # Add titles and labels
    plt.title(title)
    plt.xlabel('iteration')
    plt.ylabel('parameter length')

    # Display the plot
    plt.show()
  i = i+1


