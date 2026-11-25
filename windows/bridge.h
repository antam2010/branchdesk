/* The browser connects exclusively to a Windows loopback socket. Only complete,
   bounded HTTP requests enter the private pipe to this instance's WSL worker. */
#define HEADER_LIMIT 32768
#define BODY_LIMIT 2000000
static SOCKET listener=INVALID_SOCKET;
static HANDLE request_lock, worker_input, worker_output;
static LONG clients;
static unsigned short desktop_port;

static BOOL read_exact(HANDLE pipe, void *dest, DWORD n) {
    char *p=(char *)dest;
    while(n) {
        DWORD got=0;
        if(!ReadFile(pipe,p,n,&got,NULL) || !got) return FALSE;
        p+=got; n-=got;
    }
    return TRUE;
}
static BOOL send_exact(SOCKET s,const char *p,int n) {
    while(n) {
        int sent=send(s,p,n,0);
        if(sent<=0) return FALSE;
        p+=sent; n-=sent;
    }
    return TRUE;
}
static BOOL header_name(const char *p,int len,const char *name) {
    int i=0;
    for(;name[i] && i<len;i++) {
        char c=p[i];
        if(c>='A' && c<='Z') c=(char)(c+'a'-'A');
        if(c!=name[i]) return FALSE;
    }
    return !name[i] && i<len && p[i]==':';
}
/* The UI sends fixed-length GET/POST requests. Reject ambiguous lengths. */
static int body_length(const char *head,int n) {
    int length=0;
    BOOL seen=FALSE;
    for(int start=0;start<n;) {
        int end=start;
        while(end+1<n && !(head[end]=='\r' && head[end+1]=='\n')) end++;
        if(end+1>=n) return -1;
        if(header_name(head+start,end-start,"transfer-encoding")) return -1;
        if(header_name(head+start,end-start,"content-length")) {
            int i=start+15;
            if(seen) return -1;
            seen=TRUE;
            while(i<end && (head[i]==' '||head[i]=='\t')) i++;
            if(i==end || head[i]<'0'||head[i]>'9') return -1;
            while(i<end && head[i]>='0' && head[i]<='9') {
                length=length*10+head[i++]-'0';
                if(length>BODY_LIMIT) return -1;
            }
            while(i<end && (head[i]==' '||head[i]=='\t')) i++;
            if(i!=end) return -1;
        }
        start=end+2;
    }
    return length;
}
static DWORD WINAPI serve_client(void *arg) {
    SOCKET s=(SOCKET)(UINT_PTR)arg;
    HANDLE heap=GetProcessHeap();
    char *buf=(char *)HeapAlloc(heap,0,HEADER_LIMIT);
    int used=0,end=0;
    if(!buf) goto done;
    while(!end && used<HEADER_LIMIT) {
        int got=recv(s,buf+used,HEADER_LIMIT-used,0);
        if(got<=0) goto done;
        int begin=used>3?used-3:0;
        used+=got;
        for(int i=begin;i+3<used;i++)
            if(buf[i]=='\r' && buf[i+1]=='\n' && buf[i+2]=='\r' && buf[i+3]=='\n') { end=i+4; break; }
    }
    if(!end) goto done;
    int body=body_length(buf,end);
    if(body<0) goto done;
    DWORD size=(DWORD)(end+body);
    if(size>HEADER_LIMIT) {
        char *larger=(char *)HeapReAlloc(heap,0,buf,size);
        if(!larger) goto done;
        buf=larger;
    }
    while((DWORD)used<size) {
        int got=recv(s,buf+used,(int)size-used,0);
        if(got<=0) goto done;
        used+=got;
    }
    if(WaitForSingleObject(request_lock,INFINITE)!=WAIT_OBJECT_0) goto done;
    DWORD remaining=0;
    BOOL ok=write_all(worker_input,(unsigned char *)&size,4) &&
        write_all(worker_input,(unsigned char *)buf,size) && read_exact(worker_output,&remaining,4);
    BOOL connected=TRUE;
    while(ok && remaining) {
        DWORD chunk=remaining<HEADER_LIMIT?remaining:HEADER_LIMIT;
        ok=read_exact(worker_output,buf,chunk);
        if(ok && connected) connected=send_exact(s,buf,(int)chunk);
        remaining-=chunk;
    }
    ReleaseMutex(request_lock);
done:
    if(buf) HeapFree(heap,0,buf);
    shutdown(s,SD_SEND);
    closesocket(s);
    InterlockedDecrement(&clients);
    return 0;
}
static DWORD WINAPI accept_clients(void *unused) {
    (void)unused;
    for(;;) {
        SOCKET s=accept(listener,NULL,NULL);
        if(s==INVALID_SOCKET) break;
        DWORD timeout=10000;
        setsockopt(s,SOL_SOCKET,SO_RCVTIMEO,(const char *)&timeout,sizeof(timeout));
        setsockopt(s,SOL_SOCKET,SO_SNDTIMEO,(const char *)&timeout,sizeof(timeout));
        HANDLE thread=NULL;
        if(InterlockedIncrement(&clients)<=32)
            thread=CreateThread(NULL,0,serve_client,(void *)(UINT_PTR)s,0,NULL);
        if(thread) CloseHandle(thread);
        else { InterlockedDecrement(&clients); closesocket(s); }
    }
    return 0;
}
static BOOL listen_local(void) {
    WSADATA ws;
    struct sockaddr_in addr={0};
    int len=sizeof(addr);
    int exclusive=1;
    if(WSAStartup(MAKEWORD(2,2),&ws)) return FALSE;
    addr.sin_family=AF_INET;
    addr.sin_addr.s_addr=htonl(INADDR_LOOPBACK);
    listener=socket(AF_INET,SOCK_STREAM,IPPROTO_TCP);
    if(listener==INVALID_SOCKET ||
        setsockopt(listener,SOL_SOCKET,SO_EXCLUSIVEADDRUSE,(const char *)&exclusive,sizeof(exclusive)) ||
        bind(listener,(struct sockaddr *)&addr,len) || listen(listener,SOMAXCONN) ||
        getsockname(listener,(struct sockaddr *)&addr,&len)) return FALSE;
    desktop_port=ntohs(addr.sin_port);
    request_lock=CreateMutexW(NULL,FALSE,NULL);
    return request_lock!=NULL;
}
static BOOL check_local(void) {
    struct sockaddr_in addr={0};
    addr.sin_family=AF_INET; addr.sin_port=htons(desktop_port); addr.sin_addr.s_addr=htonl(INADDR_LOOPBACK);
    SOCKET s=socket(AF_INET,SOCK_STREAM,IPPROTO_TCP);
    if(s==INVALID_SOCKET) return FALSE;
    DWORD timeout=12000;
    setsockopt(s,SOL_SOCKET,SO_RCVTIMEO,(const char *)&timeout,sizeof(timeout));
    char req[128], reply[2048];
    int n=wsprintfA(req,"GET /_ready HTTP/1.0\r\nHost: 127.0.0.1:%u\r\n\r\n",(unsigned)desktop_port);
    BOOL ok=!connect(s,(struct sockaddr *)&addr,sizeof(addr)) && send_exact(s,req,n);
    int used=0;
    while(ok && used<(int)sizeof(reply)-1) {
        int got=recv(s,reply+used,(int)sizeof(reply)-1-used,0);
        if(got<=0) { ok=got==0; break; }
        used+=got;
    }
    reply[used]=0;
    closesocket(s);
    return ok && used>=(int)(sizeof("branchdesk-ready")-1) && !lstrcmpA(reply+used-(sizeof("branchdesk-ready")-1),"branchdesk-ready");
}
