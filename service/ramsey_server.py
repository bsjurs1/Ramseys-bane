import socket 
from threading import Thread 
import time
import threading
import json, sys
import logging
import random
from db_store import DBStore
from read_write_lock import RWLock
from subprocess import call
import os
import copy
from multiprocessing.pool import ThreadPool
import multiprocessing
import traceback
from Queue import Queue

######################Constants######################

LOCALHOST = '127.0.0.1'
DB_NAME = 'ramseys_bane'
DB_USER = 'ramsey'
COUNTER_EX_TABLE = 'counter_examples'
BUFFER_SIZE = 1024*1024
COUNTER_EX_DIR = 'counter_examples'
MAX_CLIQUE_CNT = 999
NO_OF_SERVERS = 7
NUM_OF_THREADS = 3000

######################################################

class RamseyServer():
    def __init__(self, svrId):
        self.svrId = svrId
        ''' The below variables hold the 'bestCliqueCount' lowest clique count seen for the 
        graph 'bestGraph' with 'nodes' number of nodes.
        The 'indexQueue' holds the indices of in the graph that has edge value 1.
        The 'timeout' variable holds max time an isomorph of graph can take to find a better 
        clique count '''
        self.bestCliqueCount = MAX_CLIQUE_CNT
        self.currCounterNum = 0
        self.bestGraph = ''
        self.nodes = 0
        self.indexQueue = []
        self.timeout = None

        self.lock = threading.Lock()
        self.rwl = RWLock()
        svrInfo= {'svr_name':self.svrId.upper()}
        self.logger = self.logFormatter(svrInfo)

        self.loadConfig()
        self.initDbConnection()
        self.setbestCliqueCountFromDB()

        self.startServer()


    def loadConfig(self):
        with open('config.json') as config_file:    
            self.config = json.load(config_file)


    def initDbConnection(self):

        db_node = random.choice(self.config['db_nodes'])
        self.logger.debug('Connecting to DB: %s' %db_node)
        self.db = DBStore(DB_NAME, DB_USER, db_node)

        create_table = 'CREATE TABLE IF NOT EXISTS '+ COUNTER_EX_TABLE 
        create_table += ' (counterNum INT PRIMARY KEY, cliqueCount INT, currIndex INT, bestGraph VARCHAR)'
        self.db.create(create_table)


    def setbestCliqueCountFromDB(self):
        '''Read from db and update in best counter example value found so far'''

        get_statement = 'SELECT * FROM ' + COUNTER_EX_TABLE + ' WHERE counterNum=(SELECT MAX(counterNum) from ' + COUNTER_EX_TABLE + ')'
        rows = self.db.get(get_statement)
        if rows:
            row = rows[0]
            self.setCurrCounterNum(int(row[0]))
            self.setBestCliqueCount(int(row[1]))
            self.setBestGraph(row[3])
            self.fillIndexQueue()

            self.logger.debug('Loaded the best counter example number from db: %d' %(row[0]))


    def logFormatter(self, svrInfo):
        '''Logging info'''
        logger = logging.getLogger()
        logger.setLevel(logging.DEBUG)
        logging.basicConfig(filename='server.log',level=logging.DEBUG)
        ch = logging.StreamHandler()
        formatter = logging.Formatter('%(svr_name)s: %(message)s')
        ch.setFormatter(formatter)
        logger.addHandler(ch)
        logger = logging.LoggerAdapter(logger, svrInfo)
        return logger

############################## Getter and setter methods ##################################################

    def getBestCliqueCount(self):
        #self.rwl.acquire_read()
        bestCliqueCount = self.bestCliqueCount
        #self.rwl.release()

        return bestCliqueCount


    def getBestGraph(self):
        #self.rwl.acquire_read()
        bestGraph = self.bestGraph
        #self.rwl.release()
        if not bestGraph:
            return []
        return bestGraph


    def getIndexQueue(self):
        #self.rwl.acquire_read()
        indexQueue = self.indexQueue
        #self.rwl.release()

        return indexQueue


    def getCurrCounterNum(self):
        #self.rwl.acquire_read()
        counterNum = self.currCounterNum
        #self.rwl.release()

        return counterNum


    def setBestCliqueCount(self, bestCliqueCount):
        #self.rwl.acquire_write()
        self.bestCliqueCount = bestCliqueCount
        #self.rwl.release()


    def setCurrCounterNum(self, counterNum):
        #self.rwl.acquire_write()
        self.currCounterNum = counterNum
        #self.rwl.release()


    def setIndexQueue(self, indexQueue):
        #self.rwl.acquire_write()
        self.indexQueue = copy.deepcopy(indexQueue)
        #self.rwl.release()


    def setBestGraph(self, graph):
        #elf.rwl.acquire_write()
        if graph:
            self.bestGraph = copy.deepcopy(graph)
        else:
            self.bestGraph = ''
        #self.rwl.release()


    def getAndSetNextIndex(self):
        ''' Treat indexQueue like a queue; pop the index on which client should work on.
        Update the index in the db'''
        nextIdx = -1
        self.rwl.acquire_write()
        if len(self.indexQueue) > 0:
            randIdx = random.randint(0, len(self.indexQueue)-1)
            nextIdx = self.indexQueue.pop(randIdx)
        self.rwl.release()        

        return nextIdx


############################## DB methods ##################################################

    def insertIntoDB(self, counterNum, cliqueCnt, graph, index=-1):
        rows = self.readFromDB(counterNum)
        if rows:
            self.updateStateOnDB(counterNum, cliqueCnt, graph)
        else:
            insert_statement = 'INSERT INTO '+ COUNTER_EX_TABLE + ' (counterNum, cliqueCount, currIndex, bestGraph) VALUES (%d, %d, %d, \'%s\')' % \
            (counterNum, cliqueCnt, index, graph)
            self.db.insert(insert_statement)


    def updateStateOnDB(self, counterNum, cliqueCnt, graph, index=-1):

        update_statement = 'UPDATE '+ COUNTER_EX_TABLE + ' SET cliqueCount=%d, currIndex=%d, bestGraph=\'%s\' WHERE counterNum=%d' % \
        (cliqueCnt, index, graph, counterNum)
        self.db.update(update_statement)


    def readFromDB(self, counterNum):
        get_statement = 'SELECT * FROM ' + COUNTER_EX_TABLE + ' WHERE counterNum=%d' %counterNum
        rows = self.db.get(get_statement)
        if not rows:
            return None
        row = rows[0]
        counterNum, bestCliqueCount, bestGraph = row[0], row[1], row[3]
        return counterNum, bestCliqueCount, bestGraph


    def readMaxNumFromDB(self):
        get_statement = 'SELECT * FROM ' + COUNTER_EX_TABLE + ' WHERE counterNum=(SELECT MAX(counterNum) from ' + COUNTER_EX_TABLE + ')'
        rows = self.db.get(get_statement)
        row = rows[0]
        counterNum, bestCliqueCount, bestGraph = row[0], row[1], row[3]
        return counterNum, bestCliqueCount, bestGraph

############################## Helper methods ##################################################

    def fillIndexQueue(self):
        '''Fill the queue with indices in the graph that has edge value 1'''

        tmpIdxQueue = []
        ''' If the current clique count is 0, then the counter ex is found and no more indexes to be queued
        for that counter_ex number.'''
        if self.bestCliqueCount != 0:
            tmpGraph = self.bestGraph
            length, cnt = len(tmpGraph), 1

            svrNum = int(self.svrId[-1])
            for i in range(length):
                if tmpGraph[i] == '1':
                    if (cnt%NO_OF_SERVERS == svrNum-1):
                        tmpIdxQueue.append(i)
                    cnt += 1
        self.setIndexQueue(tmpIdxQueue)


    def isGraphsEqualToBestGraph(self, g1):
        '''Check if the two graphs passed (list of edge weights) are equal'''
        g2 = self.getBestGraph()
        g1Len, g2Len = len(g1), len(g2)
        if g1Len != g2Len:
            return False

        for i in range(g1Len):
            if g1[i] != g2[i]:
                return False

        return True


    def updateState(self, counterNum, cliqueCnt, graph, writeToDB=True, forceUpdate=False):
        self.rwl.acquire_write()
        if counterNum > self.currCounterNum or (counterNum == self.currCounterNum and cliqueCnt < self.bestCliqueCount)\
        or forceUpdate:
            '''Update current cunter num, clique count and graph.'''
            self.setCurrCounterNum(counterNum)
            self.setBestCliqueCount(cliqueCnt)

            ''' If a counter ex was found for the currCounterNum, new graph must be constructed
            based on the current counter ex'''
            
            self.setBestGraph(graph)
            self.fillIndexQueue()

            if writeToDB:
                self.insertIntoDB(counterNum, cliqueCnt, graph)
        self.rwl.release()


    def updateStateFromDB(self):
        '''Read variables from DB; update any variable that has been modified by other servers'''
        counterNum, bestCliqueCount, bestGraph = self.readMaxNumFromDB()

        updateState = False
        
        if counterNum > self.getCurrCounterNum():
            updateState = True

        elif bestCliqueCount < self.getBestCliqueCount() and counterNum == self.getCurrCounterNum():
            updateState = True

        if updateState:
            self.updateState(counterNum, bestCliqueCount, bestGraph, writeToDB=False)


    def replyToClient(self, conn, clientIndex):
        '''Making sure that always the latest counter example value is sent to the client'''
        self.updateStateFromDB()
        if clientIndex == 1:
            newIndex = self.getAndSetNextIndex()
        else:
            newIndex = -1
        self.rwl.acquire_read()
        counterNum, cliqueCnt, bestGraph = self.currCounterNum, self.bestCliqueCount, self.bestGraph
        self.rwl.release()

        reply = str(counterNum) + ':' + str(cliqueCnt) 
        reply +=  ':' + str(newIndex) + ':' + bestGraph

        #self.logger.debug('Reply message: %d, %d, %d' %(counterNum, cliqueCnt, newIndex))
        conn.send(reply)
        #time.sleep(2)
        conn.close()


    def handleNewCounterExample(self, conn, msg):

        '''The first part of input string is the current counter example computed by the client'''
        counterNum, cliqueCnt, clientIndex, graph = msg.split(':')
        try:
            counterNum = int(counterNum)
            cliqueCnt = int(cliqueCnt)
            clientIndex = int(clientIndex)
        except Exception as e:
            '''In case client didn't in right format; ignore that int conversion and set currNum to 0'''
            self.logger.debug('Encountered error: %s' %e)
            raise

        if counterNum == self.getCurrCounterNum():
            if cliqueCnt == 0:
                '''If cliqueCount = 0 then the counter ex for the currCounterNum was found.
                 So everyone should start working on the next counterNum. '''

                '''Store the counter ex graph in DB; we don't care about index'''
                self.updateState(counterNum, cliqueCnt, graph)
                
                logMsg = 'Found counter example for: %d' %(counterNum)
                self.logger.debug(logMsg)
                self.postOnSlack()

            elif cliqueCnt <= self.getBestCliqueCount() and not self.getIndexQueue() and not self.isGraphsEqualToBestGraph(graph):
                ''' Found a graph with better clique count '''
                self.updateState(counterNum, cliqueCnt, graph)
                logMsg = 'Found better clique count %d for counter number %d' %(cliqueCnt, counterNum)
                self.logger.debug(logMsg)

            elif self.getBestCliqueCount() != 0 and not self.getIndexQueue() and not self.isGraphsEqualToBestGraph(graph):
                '''No more index to distribute; accept any graph not same as old one'''
                self.updateState(counterNum, cliqueCnt, graph, forceUpdate=True)

        elif counterNum > self.getCurrCounterNum():
            self.updateState(counterNum, cliqueCnt, graph)

        self.replyToClient(conn, clientIndex)

##################################### Misc methods ########################################################

    def getServerIpPort(self, svrId):
        '''Get ip and port on which server is listening from config'''
        return self.config['servers'][svrId][0], self.config['servers'][svrId][1]


    def createExampleFile(self, currNum, graph):
        try:
            if not os.path.exists(COUNTER_EX_DIR):
                os.makedirs(COUNTER_EX_DIR)
            f= open(COUNTER_EX_DIR + '/' + str(currNum) + '.txt','w+')
            f.write(graph)
            f.close()
        except Exception as e:
            self.logger.debug(e)
            self.logger.debug('Some error while writing to file! Ignoring it!')


    def postOnSlack(self):
        
        currNum, graph = self.getCurrCounterNum(), self.getBestGraph()
        self.createExampleFile(currNum, graph)
        try:
            cmd = 'curl -F file=@' + COUNTER_EX_DIR + '/' + str(currNum) + '.txt'
            cmd += ' -F channels=#counter_examples -F token=xoxp-168043439156-168044120404-175871744339-d470018d55873ffc1f59b0e8b1d42f17'
            cmd += ' https://slack.com/api/files.upload'
            # cmd = "curl -X POST -H 'Content-type: application/json' --data '{\"text\":\""
            # cmd += str(self.bestCliqueCount) + "-" + self.bestGraph 
            # cmd += "\"}' API_WEBHOOK"
            
            os.system(cmd)
        except Exception as e:
            self.logger.debug(e)
            self.logger.debug('Some error while posting on Slack! Ignoring it!')
        

####################################################################################### 

    # Multithreaded Python server : TCP Server Socket Thread Pool
    class ConnectionThread(Thread): 
     
        def __init__(self, conn, ip, port, srvr): 
            Thread.__init__(self) 
            self.ip = ip
            self.port = port
            self.conn = conn
            self.srvr = srvr


    def runNewClientConn(self, q):
        while True:
            items = q.get()
            conn, recvMsg = items[0], ''
            data = conn.recv(BUFFER_SIZE)

            try:
                counterNum, cliqueCnt, index, _ = data.split(':')
            
                '''The msg will be ==> counter_num:clique_count:index:matrix'''
                dataSize = len(counterNum) + len(cliqueCnt) + len(index) + int(counterNum)*int(counterNum) + 3
                
                while len(data) < dataSize:
                    data += conn.recv(BUFFER_SIZE)

                #self.logger.debug('Received message: %s, %s, %s, %s' %(counterNum, cliqueCnt, index, threading.current_thread()))

                self.handleNewCounterExample(conn, data)

                q.task_done()

            except Exception as e:
                self.logger.debug('Encountered error: %s' %e)
                traceback.print_exc()
                conn.close()
                q.task_done()
        '''Kill the thread after use'''
        #sys.exit()


    def startServer(self):
        ip, port = self.getServerIpPort(self.svrId)

        pool = multiprocessing.pool.ThreadPool(int(NUM_OF_THREADS), self.runNewClientConn ,(q,))

        tcpServer = socket.socket(socket.AF_INET, socket.SOCK_STREAM) 
        tcpServer.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) 
        tcpServer.bind((ip, port))

        self.logger.debug('Server ready to listen on (%s:%d)' %(ip, port))
        while True: 
            tcpServer.listen(4) 
            (conn, (cliIP,cliPort)) = tcpServer.accept()
            q.put([conn])
            # newthread = self.ConnectionThread(conn, cliIP, cliPort, self) 
            # newthread.start()
    
 
svrId = sys.argv[1]
q = Queue()
ramseySrvr = RamseyServer(svrId)
