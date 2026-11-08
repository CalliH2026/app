/* Read-only Win32 controls bridge for the isolated PRONOTE example bottle.
   No hooks, memory patches, input synthesis, passwords, or network requests. */
#define UNICODE
#define _UNICODE
#include <windows.h>
#include <wchar.h>
#include <stdio.h>
#include <string.h>
static FILE *out;
static int window_count=0,control_count=0;
static DWORD cutoff;
static void json_string(const wchar_t *s){
    int bytes=WideCharToMultiByte(CP_UTF8,0,s,-1,NULL,0,NULL,NULL);
    char *utf=(char*)HeapAlloc(GetProcessHeap(),0,(SIZE_T)bytes);
    if(!utf){fputs("\"\"",out);return;}
    WideCharToMultiByte(CP_UTF8,0,s,-1,utf,bytes,NULL,NULL);
    fputc('"',out);
    for(char *p=utf;*p;p++){
        unsigned char c=(unsigned char)*p;
        if(c=='"'||c=='\\'){fputc('\\',out);fputc(c,out);}
        else if(c=='\n')fputs("\\n",out);
        else if(c=='\r')fputs("\\r",out);
        else if(c=='\t')fputs("\\t",out);
        else if(c>=32)fputc(c,out);
    }
    fputc('"',out);HeapFree(GetProcessHeap(),0,utf);
}
static BOOL CALLBACK control(HWND hwnd,LPARAM unused){
    if(control_count>=120||GetTickCount()-cutoff>4000)return FALSE;
    if(!IsWindowVisible(hwnd))return TRUE;
    wchar_t kind[128]={0},text[2000]={0};GetClassNameW(hwnd,kind,128);
    /* Skip every editable field, including usernames and password controls. */
    if(wcsstr(kind,L"Edit")||wcsstr(kind,L"EDIT")||wcsstr(kind,L"ComboBox"))return TRUE;
    DWORD_PTR result=0;
    SendMessageTimeoutW(hwnd,WM_GETTEXT,1999,(LPARAM)text,SMTO_ABORTIFHUNG|SMTO_BLOCK,35,&result);
    if(text[0]){
        if(control_count++)fputc(',',out);
        fputs("{\"class\":",out);json_string(kind);fputs(",\"text\":",out);json_string(text);fputc('}',out);
    }
    return TRUE;
}
static BOOL CALLBACK window(HWND hwnd,LPARAM unused){
    if(window_count>=8||GetTickCount()-cutoff>4500)return FALSE;
    if(!IsWindowVisible(hwnd))return TRUE;
    DWORD pid=0;GetWindowThreadProcessId(hwnd,&pid);
    HANDLE process=OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION,FALSE,pid);
    if(!process)return TRUE;
    wchar_t path[2048]={0};DWORD size=2047;
    BOOL found=QueryFullProcessImageNameW(process,0,path,&size);CloseHandle(process);
    if(!found)return TRUE;
    wchar_t *name=wcsrchr(path,L'\\');name=name?name+1:path;
    if(_wcsicmp(name,L"PRONOTE Monoposte.exe")&&_wcsicmp(name,L"Client PRONOTE.exe"))return TRUE;
    wchar_t title[1024]={0};GetWindowTextW(hwnd,title,1023);
    if(!title[0])return TRUE;
    if(window_count++)fputc(',',out);
    fprintf(out,"{\"pid\":%lu,\"title\":",(unsigned long)pid);json_string(title);
    fputs(",\"process\":",out);json_string(name);fputs(",\"controls\":[",out);
    control_count=0;EnumChildWindows(hwnd,control,0);fputs("]}",out);return TRUE;
}
int wmain(int argc,wchar_t **argv){
    if(argc!=2)return 2;
    out=_wfopen(argv[1],L"wb");if(!out)return 3;
    cutoff=GetTickCount();fputs("{\"method\":\"win32_controls\",\"windows\":[",out);
    EnumWindows(window,0);fputs("]}",out);fclose(out);return 0;
}
