(function () {
  var CONFIG = { signupUrl: '/Login/NewAge.aspx' };   // form action is set on <form id="loginForm">
  var $ = function (id) { return document.getElementById(id); };
  var months = ['January','February','March','April','May','June','July','August','September','October','November','December'];
  var mS = $('MonthSelect'), dS = $('DaySelect'), yS = $('YearSelect');

  months.forEach(function (m, i) { mS.add(new Option(m, i + 1)); });
  for (var y = new Date().getFullYear(); y >= 1900; y--) yS.add(new Option(y, y));
  function fillDays() {
    var keep = dS.value, max = (mS.value && yS.value) ? new Date(yS.value, mS.value, 0).getDate() : 31;
    dS.length = 1;
    for (var d = 1; d <= max; d++) dS.add(new Option(d, d));
    if (keep && keep <= max) dS.value = keep;
  }
  fillDays(); mS.onchange = yS.onchange = fillDays;

  /* dropdowns: More, header Login, footer language */
  var menus = [$('moreItem'), $('login-span'), $('langTrigger')];
  function toggle(el) { var was = el.classList.contains('open'); menus.forEach(function (m) { m.classList.remove('open'); }); if (!was) el.classList.add('open'); }
  $('nav-more').onclick = function () { toggle($('moreItem')); };
  $('header-login').onclick = function () { toggle($('login-span')); };
  $('langTrigger').onclick = function (e) { if (e.target.tagName !== 'A') toggle($('langTrigger')); };
  document.addEventListener('click', function (e) {
    menus.forEach(function (m) { if (!m.contains(e.target)) m.classList.remove('open'); });
  });

  /* sign in */
  var form = $('loginForm'), err = $('loginError');
  function signIn() {
    if (!$('Username').value.trim() || !$('Password').value) {
      err.textContent = 'Please enter your username and password.'; return;
    }
    err.textContent = ''; form.submit();
  }
  $('btnSignIn').onclick = signIn;
  [$('Username'), $('Password')].forEach(function (i) {
    i.onkeydown = function (e) { if (e.key === 'Enter') { e.preventDefault(); signIn(); } };
  });

  /* sign up */
  var note = $('disclaimer'), noteText = note.textContent;
  $('btnSignUp').onclick = function () {
    if (!mS.value || !dS.value || !yS.value) {
      note.textContent = 'Please select your birthday.'; note.style.color = '#c00'; return;
    }
    note.textContent = noteText; note.style.color = '';
    location.href = CONFIG.signupUrl + '?Month=' + mS.value + '&Day=' + dS.value + '&Year=' + yS.value;
  };
})();
