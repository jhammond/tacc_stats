CC = gcc
CFLAGS = -Wall
CPPFLAGS = $(CDEBUG)
ST_OBJS := st_cpu.o st_ib.o st_job.o st_lustre.o st_mem.o st_net.o st_ps.o st_vm.o
OBJS := test.o stats.o dict.o collect_key_value_file.o collect_single.o $(ST_OBJS)

test: $(OBJS)

-include $(OBJS:%.o=.%.d)

%.o: %.c
	$(CC) -c $(CFLAGS) $(CPPFLAGS) $*.c -o $*.o
	$(CC) -MM $(CFLAGS) $(CPPFLAGS) $*.c > .$*.d

stats.h: stats.x
	sort --check stats.x
	touch stats.h

.PHONY: clean
clean:
	rm -f test $(OBJS) $(OBJS:%.o=.%.d)
