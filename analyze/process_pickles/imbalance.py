#!/usr/bin/env python

import sys
sys.path.append('../../monitor')
import datetime, glob, job_stats, os, subprocess, time
import operator
import matplotlib.pyplot as plt
import numpy
import scipy, scipy.stats
import argparse
import tspl

def main():

  parser = argparse.ArgumentParser(description='Look for imbalance between'
                                   'hosts for a pair of keys')
  parser.add_argument('threshold', help='Treshold ratio for std dev:mean',
                      nargs='?', default=0.25)
  parser.add_argument('key1', help='First key', nargs='?',
                      default='amd64_core')
  parser.add_argument('key2', help='Second key', nargs='?',
                      default='SSE_FLOPS')
  parser.add_argument('filearg', help='File, directory, or quoted'
                      ' glob pattern', nargs='?',default='jobs')
  parser.add_argument('-f', help='Set full mode', action='store_true')
  n=parser.parse_args()

  filelist=tspl.getfilelist(n.filearg)

  ratios={} # Place to store per job ranking metric
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

    if not tspl.checkjob(ts,3600,16): # 1 hour, 16way only
      continue
    elif ts.numhosts < 2: # At least 2 hosts
      print ts.j.id + ': 1 host'
      continue

    tmid=(ts.t[:-1]+ts.t[1:])/2.0
    rng=range(1,len(tmid))
    tmid=tmid[rng]

    maxval=numpy.zeros(len(rng))
    minval=numpy.ones(len(rng))*1e100

    rate=[]
    for v in ts:
      rate.append(numpy.divide(numpy.diff(v)[rng],
                               numpy.diff(ts.t)[rng]))
      maxval=numpy.maximum(maxval,rate[-1])
      minval=numpy.minimum(minval,rate[-1])

    vals=[]
    mean=[]
    std=[]
    for j in range(len(rng)):
      vals.append([])
      for v in rate:
        vals[j].append(v[j])
      mean.append(scipy.stats.tmean(vals[j]))
      std.append(scipy.stats.tstd(vals[j]))
      
    imbl=maxval-minval
    ratio=numpy.divide(std,mean)
    ratio2=numpy.divide(imbl,maxval)
    # Compute y-axis min and max, expand the limits by 10%
    ymin=min(numpy.minimum(ratio,ratio2))
    ymax=max(numpy.maximum(ratio,ratio2))
    ymin,ymax=tspl.expand_range(ymin,ymax,0.1)

    var=scipy.stats.tmean(ratio) # mean of ratios is the threshold statistic

    # Save away a list of ratios per user
    ratios[ts.j.id]=[var,ts.j.acct['owner']] 
    print ts.j.id + ': ' + str(var)
    # If over the threshold, plot this job
    if abs(var) > float(n.threshold):
      print '---------------------'
      fig,ax=plt.subplots(2,1,figsize=(8,8),dpi=80)
      ax[0].plot(tmid/3600,ratio)
      ax[0].hold=True
      ax[0].plot(tmid/3600,ratio2)
      ax[0].legend(('Std Dev','Max Diff'), loc=4)
      ax[1].hold=True
      ymin1=0. # This is wrong in general, but we don't want the min to be > 0.
      ymax1=0.
      for v in rate:
        ymin1=min(ymin1,min(v))
        ymax1=max(ymax1,max(v))
        ax[1].plot(tmid/3600,v)

      ymin1,ymax1=tspl.expand_range(ymin1,ymax1,0.1)

      title=ts.title + ', V: %(V)-8.3g' % {'V' : var}
      ax[0].set_title(title)
      ax[0].set_xlabel('Time (hr)')
      ax[0].set_ylabel('Imbalance Ratios')
      ax[1].set_xlabel('Time (hr)')
      ax[1].set_ylabel('Total ' + ts.label(ts.k1[0],ts.k2[0]) + '/s')
      ax[0].set_ylim(bottom=ymin,top=ymax)
      ax[1].set_ylim(bottom=ymin1,top=ymax1)

      fname='_'.join(['graph',ts.j.id,ts.k1[0],ts.k2[0],'imbalance'+full])
      fig.savefig(fname)
      plt.close()

  # Find the top bad users and their jobs
  users={}
  for k in ratios.keys():
    u=ratios[k][1]
    if not u in users:
      users[u]=[]
      users[u].append(0.)
      users[u].append([])
    else:
      users[u][0]=max(users[u][0],ratios[k][0])
      users[u][1].append(k)

  a=[ x[0] for x in sorted(users.iteritems(),
                           key=operator.itemgetter(1), reverse=True) ]
  maxi=len(a)+1
  maxi=min(10,maxi)
  print '---------top 10----------'
  for u in a[0:maxi]:
    print u + ' ' + str(users[u][0]) + ' ' + ' '.join(users[u][1])

if __name__ == '__main__':
  main()
  
