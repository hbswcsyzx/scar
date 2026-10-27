def f(x):
    return x+1
def run(n):
    total=0
    for i in range(n):
        total+=f(i)
    return total
