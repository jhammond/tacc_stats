import os, stat, glob

# Check a TSPickleLoader object to see if its job has a minimum run time and has
# its wayness in a list
def checkjob(ts, minlen, way):
  if ts.t[len(ts.t)-1] < minlen:
    print ts.j.id + ': %(time)8.3f' % {'time' : ts.t[len(ts.t)-1]/3600} \
          + ' hours'
    return False
  elif getattr(way, '__iter__', False):
    if ts.wayness not in way:
      print ts.j.id + ': skipping ' + str(ts.wayness) + '-way'
      return False
  elif ts.wayness != way:
    print ts.j.id + ': skipping ' + str(ts.wayness) + '-way'
    return False
  return True

# Generate a list of files from a command line arg. If filearg is a glob
# pattern, glob it, if it's a directory, then add '/*' and glob that, otherwise
# treat it as a single file and return a list of that
    
def getfilelist(filearg):
  filelist=glob.glob(filearg)
  if len(filelist)==1:
    mode=os.stat(filearg).st_mode
    if stat.S_ISDIR(mode):
      filelist=glob.glob(filearg+'/*')
    else:
      filelist=[filearg]
  return filelist

# Center, expand, and decenter a range
def expand_range(xmin,xmax,factor):
  xc=(xmin+xmax)/2.
  return [(xmin-xc)*(1.+factor)+xc,
          (xmax-xc)*(1.+factor)+xc]

# Adjust limits using above
def adjust_yaxis_range(ax,factor=0.1,zero_set=0.):
  ymin,ymax=ax.get_ylim()
  ymin=min(ymin,zero_set)
  ymin,ymax=expand_range(ymin,ymax,factor)
  ax.set_ylim(ymin,ymax)
