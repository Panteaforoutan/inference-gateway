import collections
import asyncio

waiting = collections.deque()
n_slots = 4
MAX = n_slots
in_flight = 0


async def acquire():
    global in_flight
    if in_flight < MAX:
        in_flight += 1
        return 
    loop = asyncio.get_running_loop()
    future = loop.create_future()   
    waiting.append(future)         # get in line
    try: 
        await future                   # pause until release() hands us a slot
    except:
        if future.done() and not future.cancelled():
            release() 
        raise
        
        
 
def release():
    global in_flight
    while waiting: 
        future = waiting.popleft()  # oldest waiter first
        if future.done(): 
            continue
        future.set_result(None)
        return 
    in_flight -= 1
