/* Read-only window metadata for the isolated PRONOTE demo and its children.
   No hooks, input synthesis, process memory reads or editable control values. */
#define UNICODE
#define _UNICODE
#include <windows.h>
#include <tlhelp32.h>
#include <stdint.h>
#include <wchar.h>
#include <stdio.h>

typedef struct { DWORD pid, parent; BOOL relevant; wchar_t name[MAX_PATH]; } Process;
static Process processes[1024];
static int process_count=0, window_count=0, control_count=0;
static FILE *out;
static DWORD started;

static void string(const wchar_t *s) {
    int n=WideCharToMultiByte(CP_UTF8,0,s,-1,NULL,0,NULL,NULL);
    char *u=HeapAlloc(GetProcessHeap(),0,(SIZE_T)n);
    if(!u){fputs("\"\"",out);return;}
    WideCharToMultiByte(CP_UTF8,0,s,-1,u,n,NULL,NULL);
    fputc('"',out);
    for(char *p=u;*p;p++) {
        unsigned char c=(unsigned char)*p;
        if(c=='"'||c=='\\'){fputc('\\',out);fputc(c,out);}
        else if(c=='\n')fputs("\\n",out);
        else if(c=='\r')fputs("\\r",out);
        else if(c=='\t')fputs("\\t",out);
        else if(c>=32)fputc(c,out);
    }
    fputc('"',out);HeapFree(GetProcessHeap(),0,u);
}

static Process *lookup(DWORD pid) {
    for(int i=0;i<process_count;i++)if(processes[i].pid==pid)return &processes[i];
    return NULL;
}

static void inventory(void) {
    HANDLE snapshot=CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS,0);
    if(snapshot==INVALID_HANDLE_VALUE)return;
    PROCESSENTRY32W entry={0};entry.dwSize=sizeof(entry);
    if(Process32FirstW(snapshot,&entry)) do {
        if(process_count==1024)break;
        Process *p=&processes[process_count++];
        p->pid=entry.th32ProcessID;p->parent=entry.th32ParentProcessID;
        wcsncpy(p->name,entry.szExeFile,MAX_PATH-1);
        p->relevant=!_wcsicmp(p->name,L"PRONOTE Monoposte.exe")||!_wcsicmp(p->name,L"Client PRONOTE.exe");
    } while(Process32NextW(snapshot,&entry));
    CloseHandle(snapshot);
    for(int pass=0;pass<6;pass++)for(int i=0;i<process_count;i++) {
        Process *parent=lookup(processes[i].parent);
        if(parent&&parent->relevant)processes[i].relevant=TRUE;
    }
}

static BOOL CALLBACK control(HWND h,LPARAM ignored) {
    if(control_count>=80||GetTickCount()-started>3500)return FALSE;
    if(!IsWindowVisible(h))return TRUE;
    wchar_t kind[200]={0},text[1400]={0};GetClassNameW(h,kind,200);
    if(wcsstr(kind,L"Edit")||wcsstr(kind,L"EDIT")||wcsstr(kind,L"ComboBox"))return TRUE;
    DWORD_PTR result=0;
    SendMessageTimeoutW(h,WM_GETTEXT,1399,(LPARAM)text,SMTO_ABORTIFHUNG|SMTO_BLOCK,25,&result);
    if(!text[0])return TRUE;
    if(control_count++)fputc(',',out);
    fputs("{\"class\":",out);string(kind);fputs(",\"text\":",out);string(text);fputc('}',out);
    return TRUE;
}

static BOOL CALLBACK window(HWND h,LPARAM ignored) {
    if(window_count>=32||GetTickCount()-started>4000)return FALSE;
    if(!IsWindowVisible(h))return TRUE;
    DWORD pid=0;GetWindowThreadProcessId(h,&pid);Process *p=lookup(pid);
    if(!p||!p->relevant)return TRUE;
    wchar_t title[2048]={0},kind[200]={0};
    GetWindowTextW(h,title,2048);GetClassNameW(h,kind,200);
    if(!title[0])return TRUE;
    HANDLE process=OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION,FALSE,pid);
    wchar_t image[2048]={0};DWORD length=2048;
    if(process){QueryFullProcessImageNameW(process,0,image,&length);CloseHandle(process);}
    if(window_count++)fputc(',',out);
    fprintf(out,"{\"hwnd\":\"%llu\",\"owner_hwnd\":\"%llu\",\"pid\":%lu,\"parent_pid\":%lu,\"foreground\":%s,\"title\":",
        (unsigned long long)(uintptr_t)h,(unsigned long long)(uintptr_t)GetWindow(h,GW_OWNER),
        (unsigned long)pid,(unsigned long)p->parent,GetForegroundWindow()==h?"true":"false");
    string(title);fputs(",\"class\":",out);string(kind);
    fputs(",\"process\":",out);string(p->name);
    fputs(",\"image_path\":",out);string(image);
    fputs(",\"controls\":[",out);control_count=0;
    EnumChildWindows(h,control,0);fputs("]}",out);return TRUE;
}

int wmain(int argc,wchar_t **argv) {
    if(argc!=2)return 2;
    out=_wfopen(argv[1],L"wb");if(!out)return 3;
    started=GetTickCount();inventory();
    fputs("{\"method\":\"win32_document_windows\",\"windows\":[",out);
    EnumWindows(window,0);fputs("]}",out);fclose(out);return 0;
}
