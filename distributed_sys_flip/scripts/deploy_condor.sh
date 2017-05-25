#!/bin/bash

cd ~/Ramseys-bane/distributed_sys_flip
git stash
git pull origin master
make clean
make

condor_rm cs293b-3
condor_submit condor_configuration1.txt
condor_submit condor_configuration2.txt
condor_submit condor_configuration3.txt
condor_submit condor_configuration4.txt