#!/usr/bin/env python
import datetime, errno, glob, gzip, numpy, os, sge_acct, sys, time

TS_TMP_DIR = os.getenv('TS_TMP_DIR', '/tmp/TS')
TS_VERBOSE = True # XXX

prog = os.path.basename(sys.argv[0])
if prog == "":
    prog = "***"

def trace(fmt, *args):
    if TS_VERBOSE:
        msg = fmt % args
        sys.stderr.write(prog + ": " + msg)

def error(fmt, *args):
    msg = fmt % args
    sys.stderr.write(prog + ": " + msg)

RAW_STATS_TIME_MAX = 86400 + 2 * 3600
RAW_STATS_TIME_PAD = 1200

SF_SCHEMA_CHAR = '!'
SF_DEVICES_CHAR = '@'
SF_COMMENT_CHAR = '#'
SF_PROPERTY_CHAR = '$'
SF_MARK_CHAR = '%'

# stats/HOST/TIMESTAMP: raw stats files.
raw_stats_dir = os.path.join(TS_TMP_DIR, 'stats')

# accounting: mirror of sge accounting file or a chunk of it.
# Only used in test.
sge_acct_path = os.path.join(TS_TMP_DIR, 'accounting')

# prolog_host_lists/YYYY/MM/DD/prolog_hostfile.JOBID.*.
# Symbolic link to /share/sge6.2/default/tacc/hostfile_logs.
prolog_host_list_dir = os.path.join(TS_TMP_DIR, 'prolog_host_lists')

def get_host_list_path(acct):
    """Return the path of the host list written during the prolog."""
    # Example: /tmp/TS/prolog_host_lists/2011/05/19/prolog_hostfile.1957000.IV32627
    start_date = datetime.date.fromtimestamp(acct['start_time'])
    base_glob = 'prolog_hostfile.' + acct['id'] + '.*'
    for days in (0, -1, 1):
        yyyy_mm_dd = (start_date + datetime.timedelta(days)).strftime("%Y/%m/%d")
        full_glob = os.path.join(prolog_host_list_dir, yyyy_mm_dd, base_glob)
        for path in glob.iglob(full_glob):
            return path
    return None


def stats_file_discard_record(file):
    for line in file:
        if line.isspace():
            return


class Schema(object):
    __slots__ = ('desc', 'entries', 'keys')

    def __init__(self, job, desc):
        self.desc = desc
        self.entries = []
        self.keys = {}
        for i, s in enumerate(desc.split()):
            e = SchemaEntry(job, i, s)
            self.keys[e.key] = e
            self.entries.append(e)

    def __eq__(self, other):
        return isinstance(other, self.__class__) and \
               all(self.__getattribute__(attr) == other.__getattribute__(attr) for attr in self.__slots__)

    def __ne__(self, other):
        return not self.__eq__(other)

class SchemaEntry(object):
    __slots__ = ('key', 'index', 'is_control', 'is_event', 'width', 'mult', 'unit')

    def __init__(self, job, i, s):
        opt_lis = s.split(',')
        self.key = opt_lis[0]
        self.index = i
        self.is_control = False
        self.is_event = False
        self.width = None
        self.mult = None
        self.unit = None
        for opt in opt_lis[1:]:
            if len(opt) == 0:
                continue
            elif opt[0] == 'C':
                self.is_control = True
            elif opt[0] == 'E':
                self.is_event = True
            elif opt[0:2] == 'W=':
                self.width = int(opt[2:])
            elif opt[0:2] == 'U=':
                j = 2
                while j < len(opt) and opt[j].isdigit():
                    j += 1
                if j > 2:
                    self.mult = numpy.uint64(opt[2:j])
                if j < len(opt):
                    self.unit = opt[j:]
                if self.unit == "KB":
                    self.mult = numpy.uint64(1024)
                    self.unit = "B"
            else:
                # XXX
                job.error("unrecognized option `%s' in schema entry spec `%s'\n", opt, s)

    def __eq__(self, other):
        return isinstance(other, self.__class__) and \
               all(self.__getattribute__(attr) == other.__getattribute__(attr) for attr in self.__slots__)

    def __ne__(self, other):
        return not self.__eq__(other)


class Host(object):
    # __slots__ = ('job', 'name', 'times', 'marks', 'raw_stats')

    def __init__(self, job, name):
        self.job = job
        self.name = name
        self.times = []
        self.marks = {}
        self.raw_stats = {}

    def trace(self, fmt, *args):
        self.job.trace('%s: ' + fmt, self.name, *args)

    def error(self, fmt, *args):
        self.job.error('%s: ' + fmt, self.name, *args)

    def get_stats_paths(self):
        raw_host_stats_dir = os.path.join(raw_stats_dir, self.name)
        job_start = self.job.start_time - RAW_STATS_TIME_PAD
        job_end = self.job.end_time + RAW_STATS_TIME_PAD
        path_list = []
        try:
            for ent in os.listdir(raw_host_stats_dir):
                base, dot, ext = ent.partition(".")
                if not base.isdigit():
                    continue
                # Prune to files that might overlap with job.
                ent_start = long(base)
                ent_end = ent_start + RAW_STATS_TIME_MAX
                if max(job_start, ent_start) <= min(job_end, ent_end):
                    full_path = os.path.join(raw_host_stats_dir, ent)
                    path_list.append((full_path, ent_start))
                    self.trace("path `%s', start %d\n", full_path, ent_start)
        except:
            pass
        path_list.sort(key=lambda tup: tup[1])
        return path_list

    def read_stats_file_header(self, start_time, file):
        schema = {}
        for line in file:
            try:
                c = line[0]
                if c == SF_SCHEMA_CHAR:
                    type_name, schema_desc = line[1:].split(None, 1)
                    # TODO schema[type_name] = self.job.get_schema(type_name, schema_desc)
                    schema[type_name] = Schema(self.job, schema_desc)
                elif c == SF_PROPERTY_CHAR:
                    pass
                elif c == SF_COMMENT_CHAR:
                    pass
                else:
                    break
            except Exception as exc:
                self.trace("file `%s', caught `%s' discarding line `%s'\n",
                           file.name, exc, line)
                break
        # TODO Remove this.
        if self.job.schema:
            # Cheesy.
            if self.job.schema != schema:
                self.error("file `%s' schema mismatch\n", file.name)
                return None
        else:
            # We win!
            self.job.schema = schema
        return schema

    def parse_stats(self, rec_time, line, schema, file):
        type_name, dev_name, rest = line.split(None, 2)
        type_schema = schema.get(type_name)
        if not type_schema:
            self.error("file `%s', unknown type `%s', discarding line `%s'\n",
                       file.name, type_name, line)
            return
        # TODO stats_dtype = numpy.uint64
        # XXX count = ?
        vals = numpy.fromstring(rest, dtype=numpy.uint64, sep=' ')
        if len(type_schema.entries) != vals.shape[0]:
            self.error("file `%s', type `%s', expected %d values, read %d, discarding line `%s'\n",
                       file.name, type_name, len(schema.entries), vals.shape[0], line)
            return
        type_stats = self.raw_stats.setdefault(type_name, {})
        dev_stats = type_stats.setdefault(dev_name, [])
        dev_stats.append((rec_time, vals))

    def read_stats_file(self, start_time, file):
        schema = self.read_stats_file_header(start_time, file)
        if not schema:
            self.trace("file `%s' bad schema\n", file.name)
            return
        # Scan file for records belonging to JOBID.
        rec_time = start_time
        for line in file:
            try:
                c = line[0]
                if c.isdigit():
                    str_time, rec_jobid = line.split()
                    rec_time = long(str_time)
                    if rec_jobid == self.job.id:
                        self.trace("file `%s' rec_time %d, rec_jobid `%s'\n",
                                   file.name, rec_time, rec_jobid)
                        self.times.append(rec_time)
                        break
            except Exception as exc:
                self.trace("file `%s', caught `%s', discarding `%s'\n",
                           file.name, str(exc), line)
                stats_file_discard_record(file)
        else:
            # We got to the end of this file wthout finding any
            # records belonging to JOBID.  Try next path.
            self.trace("file `%s' has no records belonging to job\n", file.name)
            return
        # OK, we found a record belonging to JOBID.
        for line in file:
            try:
                c = line[0]
                if c.isdigit():
                    str_time, rec_jobid = line.split()
                    rec_time = long(str_time)
                    if rec_jobid != self.job.id:
                        return
                    self.trace("file `%s' rec_time %d, rec_jobid `%s'\n",
                               file.name, rec_time, rec_jobid)
                    self.times.append(rec_time)
                elif c.isalpha():
                    self.parse_stats(rec_time, line, schema, file)
                elif c == SF_MARK_CHAR:
                    mark = line[1:].strip()
                    self.marks[mark] = True
                elif c == SF_COMMENT_CHAR:
                    pass
                else:
                    pass #...
            except Exception as exc:
                self.trace("file `%s', caught `%s', discarding `%s'\n",
                           file.name, str(exc), line)
                stats_file_discard_record(file)

    def gather_stats(self):
        path_list = self.get_stats_paths()
        if len(path_list) == 0:
            self.error("no stats files overlapping job\n")
            return False
        # read_stats_file() and parse_stats() append stats records
        # into lists of tuples in self.raw_stats.  The lists will be
        # converted into numpy arrays below.
        for path, start_time in path_list:
            with gzip.open(path) as file: # XXX Gzip.
                self.read_stats_file(start_time, file)
        # begin_mark = 'begin %s' % self.job.id # No '%'.
        # if not begin_mark in self.marks:
        #     self.error("no begin mark found\n")
        #     return False
        # end_mark = 'end %s' % self.job.id # No '%'.
        # if not end_mark in self.marks:
        #     self.error("no end mark found\n")
        #     return False
        return self.raw_stats


class Job(object):
    # TODO errors/comments
    __slots__ = ('id', 'start_time', 'end_time', 'acct', 'schema', 'hosts', 'times')

    def __init__(self, acct):
        self.id = acct['id']
        self.start_time = acct['start_time']
        self.end_time = acct['end_time']
        self.acct = acct
        self.schema = {}
        self.hosts = {}
        self.times = []

    def trace(self, fmt, *args):
        trace('%s: ' + fmt, self.id, *args)

    def error(self, fmt, *args):
        error('%s: ' + fmt, self.id, *args)

    def gather_stats(self):
        path = get_host_list_path(self.acct)
        if not path:
            self.error("no host list found\n", path)
            return False
        try:
            with open(path) as file:
                host_list = [host for line in file for host in line.split()]
        except IOError as (err, str):
            self.error("cannot open host list `%s': %s\n", path, str)
            return False
        if len(host_list) == 0:
            self.error("empty host list\n")
            return False
        for host_name in host_list:
            # TODO Keep bad_hosts.
            host = Host(self, host_name)
            if host.gather_stats():
                self.hosts[host_name] = host
        if not self.hosts:
            self.error("no good hosts\n")
            return False
        return True

    def munge_times(self):
        times_lis = []
        for host in self.hosts.itervalues():
            times_lis.append(host.times)
            del host.times
        times_lis.sort(key=lambda lis: len(lis))
        # Choose times to have median length.
        times = list(times_lis[len(times_lis) / 2])
        if not times:
            return False
        times.sort()
        # Ensure that times is sane and monotonically increasing.
        t_min = self.start_time
        for i in range(0, len(times)): 
            t = max(times[i], t_min)
            times[i] = t
            t_min = t + 1
        self.trace("nr times min %d, mid %d, max %d\n",
                   len(times_lis[0]), len(times), len(times_lis[-1]))
        self.trace("job start to first collect %d\n", times[0] - self.start_time)
        self.trace("last collect to job end %d\n", self.end_time - times[-1])
        self.times = numpy.array(times, dtype=numpy.uint64)
        return True
    
    def process_dev_stats(self, host, type_name, schema, dev_name, raw):
        def trace(fmt, *args):
            return self.trace("host `%s', type `%s', dev `%s': " + fmt,
                              host.name, type_name, dev_name, *args)
        def error(fmt, *args):
            return self.error("host `%s', type `%s', dev `%s': " + fmt,
                              host.name, type_name, dev_name, *args)
        m = len(self.times)
        n = len(schema.entries)
        A = numpy.zeros((m, n), dtype=numpy.uint64) # Output.
        # First and last of A are first and last from raw.
        A[0] = raw[0][1]
        A[m - 1] = raw[-1][1]
        k = 0
        # len(raw) may not be equal to m, so we fill out A by choosing values
        # with the closest timestamps.
        for i in range(1, m - 1):
            t = self.times[i]
            while k + 1 < len(raw) and abs(raw[k + 1][0] - t) < abs(raw[k][0] - t):
                k += 1
            A[i] = raw[k][1]
        # OK, we fit the raw values into A.  Now fixup rollover and
        # convert units.
        for j, e in enumerate(schema.entries):
            if e.is_event:
                p = r = A[0, j] # Previous raw, rollover/baseline.
                # Rebase, check for rollover.
                for i in range(0, m):
                    v = A[i, j]
                    if v < p:
                        # Looks like rollover.
                        if e.width:
                            trace("time %d, counter `%s', rollover prev %d, curr %d\n",
                                  self.times[i], e.key, p, v)
                            r -= numpy.uint64(1L << e.width)
                        elif v == 0:
                            # This happens with the IB counters.
                            # Ignore this value, use previous instead.
                            # TODO Interpolate or something.
                            trace("time %d, counter `%s', suspicious zero, prev %d\n",
                                  self.times[i], e.key, p)
                            v = p # Ugh.
                        else:
                            error("time %d, counter `%s', 64-bit rollover prev %d, curr %d\n",
                                  self.times[i], e.key, p, v)
                            # TODO Discard or something.
                    A[i, j] = v - r
                    p = v
            if e.mult:
                for i in range(0, m):
                    A[i, j] *= e.mult
        return A

    def process_stats(self):
        for host in self.hosts.itervalues():
            host.stats = {}
            for type_name, raw_type_stats in host.raw_stats.iteritems():
                type_stats = host.stats[type_name] = {}
                type_schema = self.schema[type_name]
                for dev_name, raw_dev_stats in raw_type_stats.iteritems():
                    dev_stats = self.process_dev_stats(host,
                                                       type_name, type_schema,
                                                       dev_name, raw_dev_stats)
                    type_stats[dev_name] = dev_stats
            del host.raw_stats
        # TODO Clear mult, width from schemas.
        return True
    
    def aggregate_stats(self, type_name, host_names=None, dev_names=None):
        # TODO Handle control registers.
        schema = self.schema[type_name]
        m = len(self.times)
        n = len(schema.entries)
        A = numpy.zeros((m, n), dtype=numpy.uint64) # Output.       
        nr_hosts = 0
        nr_devs = 0
        if host_names:
            host_list = [self.hosts[name] for name in host_names]
        else:
            host_list = self.hosts.itervalues()
        for host in host_list:
            type_stats = host.stats.get(type_name)
            if not type_stats:
                continue
            nr_hosts += 1
            if dev_names:
                dev_list = [type_stats[name] for name in dev_names]
            else:
                dev_list = type_stats.itervalues()
            for dev_stats in dev_list:
                A += dev_stats
                nr_devs += 1
        return (A, nr_hosts, nr_devs)


def from_acct(acct):
    """from_acct(acct)
    Construct a Job object from the SGE accounting data acct, running
    all required processing.
    """
    job = Job(acct)
    job.gather_stats() and job.munge_times() and job.process_stats()
    return job