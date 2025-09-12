# here put a loader function through the opendata API so you can make an example

# you have to link the load ds tool with the staging.py function so that it goes directly in the sandbox

# then maybe you can invent something to automatically set the function you want as the loading funciton in staging 
# or maybe not... because the user needs to implement its own loading so he needs to write some function that loades anyway...
# we'll see


# finally, you can make this better by: 
# 1) accounting for the fact that tmpfs is session dipendent - so ok it gets destroyed after each session, fine 
# - but if i want to resume a chat?? 
# 2) giving the artifact storage a proper store - S3 or smt like that