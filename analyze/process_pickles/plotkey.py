#!/usr/bin/env python

import sys
sys.path.append('../../monitor')
import datetime, glob, job_stats, os, subprocess, time
import matplotlib.pyplot as plt
import numpy
import scipy, scipy.stats
import argparse
import tspl

def main():

  parser = argparse.ArgumentParser(description='Plot a key pair for some jobs')
  parser.add_argument('key1', help='First key', nargs='?',
                      default='amd64_core')
  parser.add_argument('key2', help='Second key', nargs='?',
                      default='SSE_FLOPS')
  parser.add_argument('filearg', help='File, directory, or quoted'
                      ' glob pattern', nargs='?',default='jobs')
  parser.add_argument('-f', help='Set full mode', action='store_true')
  n=parser.parse_args(sys.argv[1:])

  filelist=tspl.getfilelist(n.filearg)

  for file in filelist:
    try:
      if n.f:
        full='_full'
        ts=tspl.TSPickleLoaderFull(file,[n.key1],[n.key2])
      else:
        full=''
        ts=tspl.TSPickleLoader(file,[n.key1],[n.key2])
    except Exception as inst:
      print type(inst)     # the exception instance
      print inst           # __str__ allows args to printed directly
      continue

    if not tspl.checkjob(ts,3600,16):
      continue
    elif ts.numhosts < 2:
      print ts.j.id + ': 1 host'
      continue

    tmid=(ts.t[:-1]+ts.t[1:])/2.0

    rate={}
    fig,ax=plt.subplots(1,1,figsize=(8,6),dpi=80)
    ax.hold=True
    mean=[]
    for v in ts:
      rate=numpy.divide(numpy.diff(v),numpy.diff(ts.t))
      mean.append(scipy.stats.tmean(rate))
      ax.plot(tmid/3600,rate)

    print ts.j.id + ': ' + str(scipy.stats.tmean(mean))

    ax.set_title(ts.title)
    ax.set_xlabel('Time (hr)')
    ax.set_ylabel('Total ' + ts.k1[0] + ' ' + ts.k2[0] + '/s')
    fname='_'.join(['graph',ts.j.id,ts.k1[0],ts.k2[0],'vs_t'+full])
    fig.savefig(fname)
    plt.close()

if __name__ == '__main__':
  main()
  
