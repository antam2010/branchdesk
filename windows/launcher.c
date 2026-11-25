#define WIN32_LEAN_AND_MEAN
#define UNICODE
#define _UNICODE
#include <winsock2.h>
#include <windows.h>
#include <shellapi.h>
#include "payload.h"
#include "setup.h"

static HICON app_icon_big=NULL, app_icon_small=NULL;
static WCHAR launcher_path[MAX_PATH]={0}, update_signal[MAX_PATH]={0};

/* Only the data pipe crosses into WSL. Git paths never pass through Win32. */
static const WCHAR bootstrap[] =
    L" --exec python3 -I -u -c \"import io,os,sys,tempfile,zipfile;"
    L"d=tempfile.TemporaryDirectory(prefix='branchdesk-');"
    L"z=zipfile.ZipFile(io.BytesIO(sys.stdin.buffer.read(" PAYLOAD_SIZE L")));"
    L"z.extractall(d.name);z.close();sys.path[:0]=[d.name,os.path.join(d.name,'windows')];"
    L"import session;session.main();d.cleanup()\"";

/* Fixed-size buffers use MAX_PATH for installed applications, and a larger
   buffer for the process command line. Each append checks the terminator. */
static BOOL append(WCHAR *dst, DWORD cap, const WCHAR *src) {
    DWORD used = (DWORD)lstrlenW(dst), n = (DWORD)lstrlenW(src);
    if (used >= cap || n >= cap-used) return FALSE;
    CopyMemory(dst+used, src, (n+1)*sizeof(WCHAR));
    return TRUE;
}
static void alert(const WCHAR *msg) {
    MessageBoxW(NULL, msg, L"Branchdesk", MB_OK | MB_ICONERROR);
}
static void close_handle(HANDLE *h) {
    if (*h) { CloseHandle(*h); *h=NULL; }
}
static BOOL find_edge(WCHAR *path) {
    static const WCHAR *const vars[] = {L"ProgramFiles(x86)", L"ProgramFiles", L"LOCALAPPDATA"};
    for (int i=0; i<3; ++i) {
        DWORD n=GetEnvironmentVariableW(vars[i],path,MAX_PATH);
        if (n && n<MAX_PATH && append(path,MAX_PATH,L"\\Microsoft\\Edge\\Application\\msedge.exe") &&
            GetFileAttributesW(path)!=INVALID_FILE_ATTRIBUTES) return TRUE;
    }
    return FALSE;
}
static BOOL start(const WCHAR *exe, WCHAR *cmd, HANDLE in, HANDLE out, PROCESS_INFORMATION *proc) {
    STARTUPINFOW si = {0};
    si.cb=sizeof(si);
    if (in) {
        si.dwFlags=STARTF_USESTDHANDLES;
        si.hStdInput=in; si.hStdOutput=out; si.hStdError=out;
    }
    if (!CreateProcessW(exe,cmd,NULL,NULL,in!=NULL,in?CREATE_NO_WINDOW:0,NULL,NULL,&si,proc)) return FALSE;
    close_handle(&proc->hThread);
    return TRUE;
}
static BOOL write_all(HANDLE pipe, const unsigned char *data, DWORD n) {
    while (n) {
        DWORD sent=0;
        if (!WriteFile(pipe,data,n,&sent,NULL) || !sent) return FALSE;
        n-=sent; data+=sent;
    }
    return TRUE;
}

#include "bridge.h"

/* A dedicated writer keeps a WSL cold start from blocking the startup timeout. */
static DWORD WINAPI send_payload(void *pipe) {
    char port[64];
    int n=wsprintfA(port,"%u\n%u\n%u\n%u\n",(unsigned)desktop_port,(unsigned)GetCurrentProcessId(),
                   (unsigned)lstrlenW(launcher_path),(unsigned)lstrlenW(update_signal));
    return write_all((HANDLE)pipe,payload,(DWORD)sizeof(payload)) &&
        write_all((HANDLE)pipe,(const unsigned char *)port,(DWORD)n) &&
        write_all((HANDLE)pipe,(const unsigned char *)launcher_path,(DWORD)lstrlenW(launcher_path)*2) &&
        write_all((HANDLE)pipe,(const unsigned char *)update_signal,(DWORD)lstrlenW(update_signal)*2)?0:1;
}
static BOOL ready_url(const char *line, WCHAR *url) {
    const char *prefix="BRANCHDESK/2 ";
    while (*prefix) if (*line++!=*prefix++) return FALSE;
    unsigned port=0, digits=0;
    while (*line>='0' && *line<='9' && digits<5) { port=port*10+(unsigned)(*line++-'0'); ++digits; }
    if (port!=desktop_port || *line++!=' ') return FALSE;
    const char *token=line;
    while ((*line>='0'&&*line<='9')||(*line>='a'&&*line<='z')||(*line>='A'&&*line<='Z')||*line=='-'||*line=='_') ++line;
    if ((*line && *line!='\r') || line-token!=43) return FALSE;
    wsprintfW(url,L"http://127.0.0.1:%u/#",port);
    int at=lstrlenW(url);
    while(token<line) url[at++]=(unsigned char)*token++;
    url[at]=0;
    return TRUE;
}
static BOOL await_ready(HANDLE output, HANDLE process, WCHAR *url) {
    char line[512];
    DWORD len=0;
    ULONGLONG deadline=GetTickCount64()+90000;
    while (GetTickCount64()<deadline) {
        DWORD available=0, got=0;
        if (!PeekNamedPipe(output,NULL,0,NULL,&available,NULL)) return FALSE;
        if (!available) {
            if (WaitForSingleObject(process,40)==WAIT_OBJECT_0) return FALSE;
            continue;
        }
        char chunk[512];
        if (!ReadFile(output,chunk,available<sizeof(chunk)?available:sizeof(chunk),&got,NULL)) return FALSE;
        for (DWORD i=0;i<got;i++) {
            if (chunk[i]=='\n') {
                line[len]=0;
                if(ready_url(line,url)) return TRUE;
                len=0;
            } else if (len<sizeof(line)-1) line[len++]=chunk[i];
        }
    }
    return FALSE;
}
static BOOL temp_profile(WCHAR *path) {
    WCHAR base[MAX_PATH], suffix[64];
    DWORD n=GetTempPathW(MAX_PATH,base);
    if (!n || n>=MAX_PATH) return FALSE;
    wsprintfW(suffix,L"Branchdesk-%lu-%lu",GetCurrentProcessId(),GetTickCount());
    return append(path,MAX_PATH-1,base) && append(path,MAX_PATH-1,suffix) && CreateDirectoryW(path,NULL);
}
/* Only the official WSL installer requests UAC; the helper stays unelevated. */
static int ensure_prerequisites(const WCHAR *directory) {
    WCHAR script[MAX_PATH]={0}, powershell[MAX_PATH], cmd[2048]={0};
    HANDLE file=NULL;
    PROCESS_INFORMATION process={0};
    STARTUPINFOW si={0};
    DWORD code=3;
    BOOL launched=FALSE;
    si.cb=sizeof(si);
    if(!append(script,MAX_PATH,directory) || !append(script,MAX_PATH,L"\\setup.ps1")) goto done;
    file=CreateFileW(script,GENERIC_WRITE,0,NULL,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,NULL);
    if(file==INVALID_HANDLE_VALUE) { file=NULL; goto done; }
    if(!write_all(file,setup_script,(DWORD)sizeof(setup_script))) goto done;
    close_handle(&file);
    DWORD n=GetSystemDirectoryW(powershell,MAX_PATH);
    if(!n || n>=MAX_PATH || !append(powershell,MAX_PATH,L"\\WindowsPowerShell\\v1.0\\powershell.exe")) goto done;
    if(!append(cmd,2048,L"powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"") ||
       !append(cmd,2048,script) || !append(cmd,2048,L"\" -Launcher \"") ||
       !append(cmd,2048,launcher_path) || !append(cmd,2048,L"\"")) goto done;
    if(!CreateProcessW(powershell,cmd,NULL,NULL,FALSE,CREATE_NO_WINDOW,NULL,NULL,&si,&process)) goto done;
    launched=TRUE;
    close_handle(&process.hThread);
    if(WaitForSingleObject(process.hProcess,INFINITE)==WAIT_OBJECT_0)
        GetExitCodeProcess(process.hProcess,&code);
done:
    close_handle(&file);
    close_handle(&process.hProcess);
    if(script[0]) DeleteFileW(script);
    if(!launched) alert(L"시작 준비 화면을 열지 못했습니다. Windows PowerShell 실행 정책이나 보안 프로그램 차단 여부를 확인하세요.");
    else if(code!=0 && code!=2 && code!=3 && code!=10 && code!=20)
        alert(L"시작 준비 도우미가 실행되지 않았습니다. Windows PowerShell 실행 정책이나 보안 프로그램 차단 여부를 확인하세요.");
    return launched && code==20 ? 2 : launched && code==0 ? 1 : 0;
}
static void remove_profile(WCHAR *path) {
    SHFILEOPSTRUCTW op={0};
    path[lstrlenW(path)+1]=0;
    op.wFunc=FO_DELETE; op.pFrom=path;
    op.fFlags=FOF_NO_UI;
    SHFileOperationW(&op);
}
struct window_search { WCHAR title[48]; HWND window; DWORD edge_pid; BOOL allow_pid; };
static BOOL CALLBACK find_window(HWND hwnd, LPARAM data) {
    struct window_search *search=(struct window_search *)data;
    WCHAR title[256],cls[64];
    DWORD pid=0;
    if(IsWindowVisible(hwnd) && GetClassNameW(hwnd,cls,64) && !lstrcmpW(cls,L"Chrome_WidgetWin_1") &&
       GetWindowTextW(hwnd,title,256)) {
        GetWindowThreadProcessId(hwnd,&pid);
        if(search->allow_pid && pid==search->edge_pid) { search->window=hwnd; return FALSE; }
        int n=lstrlenW(search->title);
        if(lstrlenW(title)>=n) {
            title[n]=0;
            if(!lstrcmpW(title,search->title)) { search->window=hwnd; return FALSE; }
        }
    }
    return TRUE;
}
static DWORD wait_window(HANDLE backend, PROCESS_INFORMATION *edge) {
    struct window_search search={0};
    search.edge_pid=edge->dwProcessId;
    wsprintfW(search.title,L"Branchdesk [%u]",(unsigned)desktop_port);
    ULONGLONG deadline=GetTickCount64()+90000;
    while(!search.window) {
        if(WaitForSingleObject(backend,200)==WAIT_OBJECT_0) return 1;
        search.allow_pid=GetTickCount64()+85000>=deadline && WaitForSingleObject(edge->hProcess,0)==WAIT_TIMEOUT;
        EnumWindows(find_window,(LPARAM)&search);
        if(!search.window && GetTickCount64()>=deadline) return 2;
    }
    if(app_icon_big) SendMessageW(search.window,WM_SETICON,ICON_BIG,(LPARAM)app_icon_big);
    if(app_icon_small) SendMessageW(search.window,WM_SETICON,ICON_SMALL,(LPARAM)app_icon_small);
    while(IsWindow(search.window)) {
        if(GetFileAttributesW(update_signal)!=INVALID_FILE_ATTRIBUTES)
            PostMessageW(search.window,WM_CLOSE,0,0);
        if(WaitForSingleObject(backend,300)==WAIT_OBJECT_0) return 1;
    }
    return 0;
}
int WINAPI wWinMain(HINSTANCE instance,HINSTANCE prev,LPWSTR args,int show) {
    (void)prev; (void)args; (void)show;
    WCHAR edge[MAX_PATH], wsl[MAX_PATH], cmd[2048]={0}, url[128], profile[MAX_PATH+1]={0};
    HANDLE child_in=NULL, input=NULL, output=NULL, child_out=NULL, writer=NULL;
    PROCESS_INFORMATION backend={0},app={0};
    SECURITY_ATTRIBUTES sa={sizeof(sa),NULL,TRUE};
    BOOL made_profile=FALSE;
    int result=1;
    DWORD path_length=GetModuleFileNameW(NULL,launcher_path,MAX_PATH);
    if(!path_length || path_length>=MAX_PATH) { alert(L"실행 파일 경로를 확인하지 못했습니다."); return 1; }
    app_icon_big=(HICON)LoadImageW(instance,MAKEINTRESOURCEW(101),IMAGE_ICON,32,32,0);
    app_icon_small=(HICON)LoadImageW(instance,MAKEINTRESOURCEW(101),IMAGE_ICON,16,16,0);
    made_profile=temp_profile(profile);
    if(!made_profile) { alert(L"시작 준비에 사용할 임시 폴더를 만들지 못했습니다."); goto cleanup; }
    if(!append(update_signal,MAX_PATH,profile) || !append(update_signal,MAX_PATH,L"\\update.signal")) goto cleanup;
    int prepared=ensure_prerequisites(profile);
    if(prepared!=1) { result=prepared==2?0:1; goto cleanup; }
    if (!find_edge(edge)) { alert(L"Microsoft Edge 설치를 확인하지 못했습니다. Branchdesk를 다시 실행하세요."); goto cleanup; }
    if(!listen_local() || !SetHandleInformation((HANDLE)listener,HANDLE_FLAG_INHERIT,0)) {
        alert(L"BD-01: Windows에서 127.0.0.1 수신 포트를 열 수 없습니다.");
        goto cleanup;
    }
    DWORD n=GetSystemDirectoryW(wsl,MAX_PATH);
    if (!n || n>=MAX_PATH || !append(wsl,MAX_PATH,L"\\wsl.exe")) goto startup_error;
    if (!CreatePipe(&child_in,&input,&sa,0) || !CreatePipe(&output,&child_out,&sa,0) ||
        !SetHandleInformation(input,HANDLE_FLAG_INHERIT,0) ||
        !SetHandleInformation(output,HANDLE_FLAG_INHERIT,0)) goto startup_error;
    if (!append(cmd,2048,L"wsl.exe") || !append(cmd,2048,bootstrap) ||
        !start(wsl,cmd,child_in,child_out,&backend)) goto startup_error;
    close_handle(&child_in); close_handle(&child_out);
    writer=CreateThread(NULL,0,send_payload,input,0,NULL);
    if (!writer || !await_ready(output,backend.hProcess,url)) goto startup_error;
    worker_input=input; worker_output=output;
    HANDLE acceptor=CreateThread(NULL,0,accept_clients,NULL,0,NULL);
    if(!acceptor) goto startup_error;
    CloseHandle(acceptor);
    if(!check_local()) {
        alert(L"BD-03: Windows에서 보낸 연결 확인 요청에 WSL Git 서비스가 응답하지 않았습니다.");
        goto cleanup;
    }
    cmd[0]=0;
    if (!append(cmd,2048,L"msedge.exe --no-first-run --no-default-browser-check --disable-background-mode --user-data-dir=\"") ||
        !append(cmd,2048,profile) || !append(cmd,2048,L"\" --app=") || !append(cmd,2048,url) ||
        !start(edge,cmd,NULL,NULL,&app)) goto startup_error;
    DWORD state=wait_window(backend.hProcess,&app);
    if(state==2) { alert(L"BD-04: Windows 연결 확인은 성공했지만 Edge에서 Branchdesk 화면을 확인하지 못했습니다."); }
    else if (state==1) {
        alert(L"BD-05: WSL 연결이 종료되었습니다. Branchdesk를 다시 열어 주세요.");
    } else { result=0; }
    goto cleanup;
startup_error:
    alert(L"BD-02: 실행 환경은 준비됐지만 WSL Git 서비스를 시작하지 못했습니다.\n\n기본 WSL 배포판을 열어 정상 동작하는지 확인한 뒤 Branchdesk를 다시 실행하세요.");
cleanup:
    if(listener!=INVALID_SOCKET) closesocket(listener);
    close_handle(&child_in); close_handle(&child_out);
    if (writer) {
        if(WaitForSingleObject(writer,0)==WAIT_TIMEOUT) CancelSynchronousIo(writer);
        WaitForSingleObject(writer,2000);
        close_handle(&writer);
    }
    close_handle(&input);  /* EOF is the backend's shutdown signal. */
    if(backend.hProcess) WaitForSingleObject(backend.hProcess,3000);
    close_handle(&output); close_handle(&backend.hProcess);
    if (app.hProcess && WaitForSingleObject(app.hProcess,1500)!=WAIT_OBJECT_0) made_profile=FALSE;
    close_handle(&app.hProcess);
    if(made_profile) remove_profile(profile);
    if(app_icon_big) DestroyIcon(app_icon_big);
    if(app_icon_small) DestroyIcon(app_icon_small);
    return result;
}
