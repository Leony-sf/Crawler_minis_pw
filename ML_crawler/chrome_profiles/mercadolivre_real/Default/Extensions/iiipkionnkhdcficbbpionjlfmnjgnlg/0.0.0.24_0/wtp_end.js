(function(){
    let curUrl = document.location.href;
    let codePrama = window.atob(curUrl.substring(curUrl.indexOf("code=")+5));

    let htmlObj = document.getElementsByTagName("html")[0];
    htmlObj.innerHTML = codePrama;
})();