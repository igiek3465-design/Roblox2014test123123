(function(){var $=function(i){return document.getElementById(i)};var m=[$('moreItem'),$('login-span'),$('langTrigger')].filter(Boolean);
function t(e){var w=e.classList.contains('open');m.forEach(function(x){x.classList.remove('open')});if(!w)e.classList.add('open')}
if($('nav-more'))$('nav-more').onclick=function(){t($('moreItem'))};
if($('header-login'))$('header-login').onclick=function(){t($('login-span'))};
$('langTrigger').onclick=function(e){if(e.target.tagName!=='A')t($('langTrigger'))};
document.addEventListener('click',function(e){m.forEach(function(x){if(!x.contains(e.target))x.classList.remove('open')})})})();
