"""Read visible text without collecting form values."""
# Read rendered text nodes only; never input values, hidden fields or scripts.
# Frames are intentionally not traversed: missing content remains a visible limit.
READ_VISIBLE = r'''
// PRONOTE keeps a hidden login form after authentication.
if ([...document.querySelectorAll('input[type="password"]')].some(input => {
    const style = getComputedStyle(input);
    return input.getClientRects().length && style.display !== 'none'
        && style.visibility !== 'hidden';
}))
    return {login:true, text:''};
const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
const lines=[]; let size=0; let node;
while((node=walker.nextNode()) && size<16000){
    const parent=node.parentElement;
    if(!parent || parent.closest('input,textarea,select,script,style,noscript,[contenteditable], [hidden], [aria-hidden="true"]')) continue;
    const style=getComputedStyle(parent);
    if(style.visibility==='hidden' || style.display==='none' || !parent.getClientRects().length) continue;
    const text=node.textContent.trim();
    if(text){lines.push(text);size+=text.length+1;}
}
return {login:false,text:lines.join('\n').slice(0,16000)};
'''
