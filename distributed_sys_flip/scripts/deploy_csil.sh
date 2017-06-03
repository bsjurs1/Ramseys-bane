#!/bin/bash
for i in {1..36}
do
	if [ "$i" -lt 10 ]
	then
		j="0$i"
	else
		j="$i"
	fi

	ssh -o "StrictHostKeyChecking no" nikolas_chaconas@cstl-$j.cs.ucsb.edu 'bash -s 4' < './deploy.sh' &
	echo "Sent to cstl-$j.cs.ucsb.edu"
	echo "Check it out here: ssh nikolas_chaconas@cstl-$j.cs.ucsb.edu"
done

echo "deployed to 36 cstl nodes"