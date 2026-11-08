#define UNICODE
#define _UNICODE
#include <windows.h>
#include <oleacc.h>
#include <oleauto.h>
#include <stdio.h>
#include <wchar.h>
#include <string>
static FILE* out;
static unsigned count=0;
static DWORD started;
static void str(const wchar_t *s){int n=WideCharToMultiByte(CP_UTF8,0,s,-1,NULL,0,NULL,NULL);std::string u(n,'\0');WideCharToMultiByte(CP_UTF8,0,s,-1,&u[0],n,NULL,NULL);fputc('"',out);for(size_t i=0;i+1<u.size();i++){unsigned char c=u[i];if(c=='"'||c=='\\'){fputc('\\',out);fputc(c,out);}else if(c=='\n')fputs("\\n",out);else if(c=='\r')fputs("\\r",out);else if(c>=32)fputc(c,out);}fputc('"',out);}
static void walk(IAccessible* a,VARIANT child,int depth){
 if(count>450||depth>12||GetTickCount()-started>7000)return;
 VARIANT state,role;VariantInit(&state);VariantInit(&role);
 a->get_accState(child,&state);a->get_accRole(child,&role);
 if(state.vt==VT_I4 && (state.lVal&(STATE_SYSTEM_PROTECTED|STATE_SYSTEM_INVISIBLE|STATE_SYSTEM_OFFSCREEN)))return;
 BSTR name=NULL,value=NULL,desc=NULL;a->get_accName(child,&name);a->get_accDescription(child,&desc);
 bool input=(role.vt==VT_I4&&(role.lVal==ROLE_SYSTEM_TEXT||role.lVal==ROLE_SYSTEM_COMBOBOX));
 if(!input)a->get_accValue(child,&value);
 if((name&&*name)||(value&&*value)||(desc&&*desc)){
   if(count++)fputc(',',out);fprintf(out,"{\"depth\":%d,\"role\":%ld,\"state\":%ld,\"name\":",depth,role.vt==VT_I4?role.lVal:0,state.vt==VT_I4?state.lVal:0);str(name?name:L"");fputs(",\"value\":",out);str(value?value:L"");fputs(",\"description\":",out);str(desc?desc:L"");fputc('}',out);
 }
 if(name)SysFreeString(name);if(value)SysFreeString(value);if(desc)SysFreeString(desc);
 if(child.vt!=VT_I4||child.lVal!=CHILDID_SELF||input)return;
 LONG n=0;if(FAILED(a->get_accChildCount(&n)))return;n=n>300?300:n;
 VARIANT *children=new VARIANT[n];LONG got=0;
 if(SUCCEEDED(AccessibleChildren(a,0,n,children,&got))){for(LONG i=0;i<got;i++){if(children[i].vt==VT_DISPATCH){IAccessible* next=NULL;if(SUCCEEDED(children[i].pdispVal->QueryInterface(IID_IAccessible,(void**)&next))){VARIANT self;VariantInit(&self);self.vt=VT_I4;self.lVal=CHILDID_SELF;walk(next,self,depth+1);next->Release();}}else if(children[i].vt==VT_I4)walk(a,children[i],depth+1);VariantClear(&children[i]);}}
 delete[] children;
}
static BOOL CALLBACK window(HWND h,LPARAM){if(!IsWindowVisible(h))return TRUE;DWORD pid;GetWindowThreadProcessId(h,&pid);HANDLE p=OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION,FALSE,pid);if(!p)return TRUE;wchar_t path[2048];DWORD size=2048;BOOL okay=QueryFullProcessImageNameW(p,0,path,&size);CloseHandle(p);if(!okay)return TRUE;wchar_t* base=wcsrchr(path,L'\\');base=base?base+1:path;if(_wcsicmp(base,L"PRONOTE Monoposte.exe"))return TRUE;wchar_t title[1024];GetWindowTextW(h,title,1024);fprintf(out,"{\"hwnd\":%llu,\"title\":",(unsigned long long)(uintptr_t)h);str(title);fputs(",\"nodes\":[",out);count=0;IAccessible* a=NULL;HRESULT result=AccessibleObjectFromWindow(h,OBJID_CLIENT,IID_IAccessible,(void**)&a);if(SUCCEEDED(result)){VARIANT self;VariantInit(&self);self.vt=VT_I4;self.lVal=CHILDID_SELF;walk(a,self,0);a->Release();}fprintf(out,"],\"hresult\":%ld}\n",(long)result);return TRUE;}
int wmain(int argc,wchar_t**argv){if(argc!=2)return 2;out=_wfopen(argv[1],L"wb");if(!out)return 3;CoInitializeEx(NULL,COINIT_APARTMENTTHREADED);started=GetTickCount();EnumWindows(window,0);CoUninitialize();fclose(out);return 0;}
