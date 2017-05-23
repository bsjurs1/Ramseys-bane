#!/bin/bash
cd ../../

make run threads=$1
sleep 5m
PROCESS=$(pgrep clique)

while [[ 1 == 1 ]]; do
	if [[ `pgrep clique` == "" ]]; then
		echo rerunning
		make run threads=$1
	else
		echo sleeping
		sleep 5m
	fi
done