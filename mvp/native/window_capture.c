/* Capture only the actual PRONOTE example window via Wine's GDI, read-only. */
#define UNICODE
#define _UNICODE
#include <windows.h>
#include <stdint.h>
#include <wchar.h>
#include <stdio.h>
static HWND target=NULL;
static BOOL valid(HWND h) {
    DWORD pid;GetWindowThreadProcessId(h,&pid);
    HANDLE process=OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION,FALSE,pid);
    if(!process)return FALSE;
    wchar_t path[2048]={0};DWORD size=2048;
    BOOL found=QueryFullProcessImageNameW(process,0,path,&size);CloseHandle(process);
    if(!found)return FALSE;
    wchar_t *name=wcsrchr(path,L'\\');name=name?name+1:path;
    if(_wcsicmp(name,L"PRONOTE Monoposte.exe"))return FALSE;
    wchar_t title[2048]={0};GetWindowTextW(h,title,2048);
    return wcsstr(title,L"Base Exemple")!=NULL;
}
static BOOL CALLBACK find(HWND h,LPARAM ignored) {
    if(IsWindowVisible(h)&&valid(h)){target=h;return FALSE;}
    return TRUE;
}
int wmain(int argc,wchar_t **argv) {
    if(argc<3||argc>4)return 2;
    if(argc==4)target=(HWND)(uintptr_t)_wcstoui64(argv[3],NULL,10);
    else EnumWindows(find,0);
    if(!target||!IsWindow(target)||!valid(target))return 3;
    RECT rect;if(!GetWindowRect(target,&rect))return 4;
    int width=rect.right-rect.left,height=rect.bottom-rect.top;
    if(width<=0||height<=0||width>4096||height>4096)return 5;
    HDC source=!_wcsicmp(argv[2],L"client")?GetDC(target):GetWindowDC(target);if(!source)return 6;
    HDC memory=CreateCompatibleDC(source);
    BITMAPINFO info={0};info.bmiHeader.biSize=sizeof(BITMAPINFOHEADER);
    info.bmiHeader.biWidth=width;info.bmiHeader.biHeight=-height;
    info.bmiHeader.biPlanes=1;info.bmiHeader.biBitCount=32;info.bmiHeader.biCompression=BI_RGB;
    void *pixels=NULL;HBITMAP bitmap=CreateDIBSection(source,&info,DIB_RGB_COLORS,&pixels,NULL,0);
    if(!bitmap){DeleteDC(memory);ReleaseDC(target,source);return 7;}
    HGDIOBJ old=SelectObject(memory,bitmap);
    BOOL okay=FALSE;
    if(!_wcsicmp(argv[2],L"printwindow"))okay=PrintWindow(target,memory,0);
    else if(!_wcsicmp(argv[2],L"wmprint")) {
        DWORD_PTR result=0;
        okay=SendMessageTimeoutW(target,WM_PRINT,(WPARAM)memory,PRF_CLIENT|PRF_CHILDREN|PRF_NONCLIENT|PRF_ERASEBKGND,SMTO_ABORTIFHUNG|SMTO_BLOCK,1000,&result)!=0;
    }else okay=BitBlt(memory,0,0,width,height,source,0,0,SRCCOPY);
    GdiFlush();
    int status=0;
    if(okay){
        FILE *file=_wfopen(argv[1],L"wb");
        if(!file)status=8;
        else {
            BITMAPFILEHEADER header={0};header.bfType=0x4d42;
            header.bfOffBits=sizeof(header)+sizeof(info.bmiHeader);
            DWORD bytes=(DWORD)width*(DWORD)height*4;
            header.bfSize=header.bfOffBits+bytes;
            fwrite(&header,sizeof(header),1,file);fwrite(&info.bmiHeader,sizeof(info.bmiHeader),1,file);
            fwrite(pixels,bytes,1,file);fclose(file);
            fprintf(stdout,"{\"hwnd\":\"%llu\",\"width\":%d,\"height\":%d,\"method\":\"%ls\"}\n",(unsigned long long)(uintptr_t)target,width,height,argv[2]);
        }
    }else status=9;
    SelectObject(memory,old);DeleteObject(bitmap);DeleteDC(memory);ReleaseDC(target,source);
    return status;
}
