#include <stdio.h>
#include <math.h>
#include <pthread.h>
#include "distributed_flip.h"
#include <stdlib.h>
#include "clique-count.h"
#include "client_protocol/client.h"
#include "matrix.h"
#include "limits.h"
#include "getcpuclockspeed.h"

int NUM_THREADS;
int bestCliqueCount = INT_MAX;
int bestNodeCount = 0;
long double CPU_CLOCK_SPEED;

pthread_rwlock_t bestCliqueCountMutex;

void initRandomGraph(int* graph, const int nodeCount){
	const int adjMatrixSize = nodeCount*nodeCount;
	bzero(graph, adjMatrixSize*sizeof(int));
	int edgesToPlaceInRow = ceil((nodeCount-1)/2);
	int edgesPlacedInRow = 0;
	int i;
	int row;

	int edgesInPreviousRow = 0;

	for(i = 0; i < nodeCount-1; i++){
		int edgeValue = 1;
		while(1){
			int randRow = i;
			int randCol = (rand() % (nodeCount-randRow-1))+randRow+1;
			edgeValue = graph[(randRow*nodeCount)+randCol];
			if(edgeValue==0){
			graph[(randRow*nodeCount)+randCol] = 1;
			edgesPlacedInRow++;
			if(edgesToPlaceInRow == edgesPlacedInRow){
				edgesPlacedInRow = 0;
				edgesToPlaceInRow = ceil((nodeCount - 1 - i)/2);
				break;
			}
			}
		}
	}
}

void printGraph(int *graph, const int nodeCount){
	int adjMatrixSize;
	int i;
	int j;
	int value;
	int cliqueCount;

	cliqueCount = CliqueCount(graph, nodeCount, cliqueCount);

	printf("%d %d", nodeCount, cliqueCount);

	adjMatrixSize = nodeCount * nodeCount;
	
	for(i = 0; i < nodeCount; i++) {
	printf("\n");
	for(j = 0; j < nodeCount; j++) {
		value = get(i, j, graph, nodeCount);
		printf("%d ", value);
	}
	}
}

void initIndexQueue(int* indexQueue, int* graph, const int indexQueueSize, const int adjMatrixSize){
	bzero(indexQueue, indexQueueSize*sizeof(int)); 
	int index;
	int indexQueueNr = 0;
	for(index = 0; index < adjMatrixSize; index++){
	if(graph[index] == 1){
		indexQueue[indexQueueNr] = index;
		indexQueueNr++;
	}
	}
}

void sendCliqueZero(int *graph, int *nodeCount, client_struct *client_info){
	printf("Found Counter Example for %d!\n", *nodeCount);

	int received_number = sendCounterExampleToCoordinator(*nodeCount, 0, 0, graph, client_info);

	if(received_number > *nodeCount) {
		*nodeCount = received_number;
	}
	pthread_rwlock_rdlock(&bestCliqueCountMutex);
	bestNodeCount = *nodeCount;
	bestCliqueCount = client_info->coordinator_return->clique_count;
	pthread_rwlock_unlock(&bestCliqueCountMutex);
}

void *findCounterExample(void* args){
	int *graph;
	int nodeCount;
	int cliqueCount;
	int index;
	int rc;
	long t;
	int i;
	int coordinator_node_count;
	int received_number;
	int random_explore_phase = 0;
	int embedded = 0;
	client_struct *client_info;
	coordinator_struct *coordinator_return;

	nodeCount = 150;
	client_info = (client_struct *)args;
	coordinator_return = client_info->coordinator_return;

	graph = (int *)malloc(sizeof(int) * LARGEST_MATRIX_SIZE);
	bzero(graph, LARGEST_MATRIX_SIZE);

	initialize_50_50(graph, nodeCount);
	printf("Beginning search on node count of %d\n", nodeCount);

	for(; nodeCount < 1000; ) {
		//only done when indices exhausted
		if(random_explore_phase) {
			printf("Beginning Random explore phase on node count %d\n", nodeCount);
			//printGraph(graph, nodeCount);

			cliqueCount = CliqueCount(graph, nodeCount, INT_MAX);
			for(i = 0; i < nodeCount/5; i++) {
				cliqueCount = randomGraphExplore(graph, nodeCount, cliqueCount);
				if(cliqueCount == 0) {
					printf("WOW random found a clique count of zero, bravo!\n");
					break;
				}
			}
		} else {
			cliqueCount = CliqueCount(graph, nodeCount, INT_MAX);
		}

		coordinator_node_count = sendCounterExampleToCoordinator(nodeCount, cliqueCount, 1, graph, client_info);
		sendCPUCycles(client_info);

		if(coordinator_node_count >= nodeCount) {
			index = coordinator_return->index;	
			nodeCount = coordinator_return->counter_number;
			cliqueCount = coordinator_return->clique_count;

			pthread_rwlock_rdlock(&bestCliqueCountMutex);
			bestNodeCount = nodeCount;
			bestCliqueCount = cliqueCount;
			pthread_rwlock_unlock(&bestCliqueCountMutex);

			// if coordinator sent us zero
			if(cliqueCount == 0) {
				printf("Embedding counter example %d into %dx%d graph\n", nodeCount, nodeCount + 1, nodeCount + 1);
				nodeCount++;
				
				//embed counter example into next index
				bzero(graph, LARGEST_MATRIX_SIZE);
				copyMatrix(coordinator_return->out_matrix, nodeCount - 1, graph, nodeCount);
				permuteLastColumn(graph, nodeCount);

				cliqueCount = CliqueCount(graph, nodeCount, INT_MAX);
				random_explore_phase = 0;
				continue;
			} else if(index == -1) {
				cliqueCount = INT_MAX;
				//we've exhausted indeces		
				random_explore_phase = 1;
				// continue to random phase
				continue;
			} else {
				printf("Solving Counter Example %d at index %d\n", nodeCount, index);
				copyGraph(client_info->coordinator_return->out_matrix, graph, nodeCount);
				random_explore_phase = 0;
			}
			printf("Continuing to Greedy Index Permute\n");
		} else {
			continue;
		}

		int count = threadedGreedyIndexPermute(graph, nodeCount, cliqueCount, index, client_info);
		cliqueCount = count > cliqueCount ? count : cliqueCount;

		pthread_rwlock_rdlock(&bestCliqueCountMutex);
		printf("best clique count is %d and old clique count is %d\n", bestCliqueCount, cliqueCount);
		if(cliqueCount == 0) {
			// send example to coordinator
			sendCliqueZero(graph, &nodeCount, client_info);
			// begin random explore phase
			random_explore_phase = 0;
		} else {
			// request another index from coordinator
			random_explore_phase = 0;
		}
		pthread_rwlock_unlock(&bestCliqueCountMutex);

	}
	return NULL;
}

int main (int argc, char *argv[]){
	int nodeCount;
	int rc;
	int t;
	int i;
	client_struct *client_info;
	NUM_THREADS = 4;
	if(argc < 2) {
		printf("Usage ./clique NUM_THREADS\n");
		exit(1);
	}
	else {
		NUM_THREADS = atoi(argv[1]);
	}
	pthread_t threads[NUM_THREADS];
	printf("\n\nYou have chosen %d Threads\n\n", NUM_THREADS);
	//useful for logging purposes
	setbuf(stdout, NULL);
	srand(time(NULL));
	pthread_rwlock_init(&bestCliqueCountMutex, NULL);

	CPU_CLOCK_SPEED = get_cpu_clock_speed();
	if(CPU_CLOCK_SPEED == 0) CPU_CLOCK_SPEED = 2600000000;

	printf("CPU CLOCK SPEED IS: %Lf\n", CPU_CLOCK_SPEED);
	for(t=0; t<NUM_THREADS; t++){
		// int nodeCount, int* graph, const int index
		printf("In main: creating thread %d\n", t);

		client_info = (client_struct*)malloc(sizeof(client_struct));
		client_info->id = t;
		client_info->coordinator_return = (coordinator_struct*)malloc(sizeof(coordinator_struct));
		createClient(client_info);

		rc = pthread_create(&threads[t], NULL, findCounterExample, (void*)client_info);
		if (rc) {
			printf("ERROR; return code from pthread_create() is %d\n", rc);
			exit(-1);
		}
	}

	for(i=0; i < NUM_THREADS; i++) {
		int error = pthread_join(threads[i],NULL);
		if (error != 0) {
			fprintf(stderr, "error joining thread\n");
		}
	}

	/* Last thing that main() should do */
	pthread_exit(NULL);
	return 0;
}
