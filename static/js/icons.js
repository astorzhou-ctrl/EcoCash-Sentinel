/* Infographic icons: one line-icon per module and per group, drawn as inline SVG (no downloads, no cost to speed). */
(function () {
  'use strict';
  var P = {
    command_center: 'M3 3h8v8H3z M13 3h8v5h-8z M13 10h8v11h-8z M3 13h8v8H3z',
    daily_tracker: 'M4 5h16v16H4z M4 10h16 M8 3v4 M16 3v4 M9 15l2 2 4-4',
    performance_analytics: 'M3 21h18 M6 21v-6 M11 21V9 M16 21v-9 M21 6l-5 4-5-3-6 5',
    board_hub: 'M12 11a3 3 0 100-6 3 3 0 000 6z M5 20c0-3.3 3-5 7-5s7 1.7 7 5 M4 12a2 2 0 100-4 M20 12a2 2 0 100-4',
    strategy_map: 'M5 21V4 M5 4h12l-2.5 4L17 12H5',
    risk_appetite: 'M3 17a9 9 0 0118 0 M12 17l5-6 M3 17h3 M18 17h3 M12 8v2',
    risk_register: 'M9 4h6v3H9z M7 5H5v16h14V5h-2 M8 12h8 M8 16h5',
    assessment_studio: 'M4 20l1-4L16 5l3 3L8 19z M13 8l3 3 M4 20h6',
    ai_insights: 'M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z M19 16l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z',
    heat_map_portfolio: 'M3 3h5v5H3z M9.5 3h5v5h-5z M16 3h5v5h-5z M3 9.5h5v5H3z M9.5 9.5h5v5h-5z M16 9.5h5v5h-5z M3 16h5v5H3z M9.5 16h5v5h-5z M16 16h5v5h-5z',
    scenario_lab: 'M9 3h6 M10 3v6l-5 9a2 2 0 002 3h10a2 2 0 002-3l-5-9V3 M8 15h8',
    emerging_radar: 'M12 3a9 9 0 100 18 9 9 0 000-18z M12 8a4 4 0 100 8 4 4 0 000-8z M12 12l6-6',
    control_library_testing: 'M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z M8.5 12l2.5 2.5 4.5-5',
    actions_issues: 'M4 6l2 2 3-3 M4 14l2 2 3-3 M12 7h8 M12 15h8',
    audit_workspace: 'M6 3h8l4 4v5 M6 3v18h6 M16 14a3 3 0 100 6 3 3 0 000-6z M18.2 20.2L21 23',
    weekly_kpi: 'M3 3v18h18 M7 15l4-4 3 3 6-7 M15 7h5v5',
    kri_monitor: 'M3 12h4l2-6 4 12 2-6h6',
    incidents_losses: 'M12 3l10 18H2z M12 10v5 M12 18h.01',
    fraud_intelligence: 'M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z M12 9a3 3 0 100 6 3 3 0 000-6z',
    speak_up_cases: 'M4 5h16v11H9l-5 4z M8 9h8 M8 12h5',
    obligations_hub: 'M12 3v18 M5 21h14 M4 7h16 M7 7l-3 7a3 3 0 006 0z M17 7l-3 7a3 3 0 006 0z',
    regulatory_change: 'M4 4v6h6 M20 20v-6h-6 M20 10a8 8 0 00-14-3 M4 14a8 8 0 0014 3',
    privacy_breach_clock: 'M6 11h12v10H6z M8 11V7a4 4 0 018 0v4 M12 15v3',
    policy_hub: 'M5 4h10a3 3 0 013 3v14H8a3 3 0 01-3-3z M5 18a3 3 0 013-3h10 M9 8h5',
    standards_hub: 'M12 3a6 6 0 100 12 6 6 0 000-12z M9 14l-2 7 5-3 5 3-2-7 M10 9l1.5 1.5L14 8',
    isms_iso_27001: 'M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z M9 11.5h6v4H9z M10.2 11.5V10a1.8 1.8 0 013.6 0v1.5',
    bcms_iso_22301: 'M4 12a8 8 0 0114-5 M20 4v4h-4 M20 12a8 8 0 01-14 5 M4 20v-4h4',
    aims_iso_42001: 'M7 7h10v10H7z M10 10h4v4h-4z M9 3v4 M15 3v4 M9 17v4 M15 17v4 M3 9h4 M3 15h4 M17 9h4 M17 15h4',
    bcm_studio: 'M3 21h18 M5 21V9l7-5 7 5v12 M10 21v-6h4v6',
    third_party_risk: 'M10 14a4 4 0 005.7 0l3-3a4 4 0 00-5.7-5.7l-1 1 M14 10a4 4 0 00-5.7 0l-3 3a4 4 0 005.7 5.7l1-1',
    cyber_it_risk: 'M3 5h18v12H3z M8 21h8 M12 17v4 M7 9l3 2-3 2 M12 13h4',
    crisis_room: 'M7 18v-6a5 5 0 0110 0v6 M5 18h14v3H5z M12 3v2 M4 7l1.5 1.5 M20 7l-1.5 1.5',
    sentinel_copilot: 'M4 5h16v11H10l-5 4v-4H4z M12 8l1 2.5 2.5 1-2.5 1-1 2.5-1-2.5-2.5-1 2.5-1z',
    document_intelligence: 'M6 3h8l4 4v14H6z M14 3v4h4 M9 12h6 M9 16h4',
    predictive_analytics: 'M12 4a8 8 0 100 16 8 8 0 000-16z M8 9c1-2 3-3 5-3 M7 21h10',
    ai_governance: 'M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z M12 8l1 2.5 2.5 1-2.5 1-1 2.5-1-2.5-2.5-1 2.5-1z',
    workflow_designer: 'M3 4h6v5H3z M15 4h6v5h-6z M9 17h6v5H9z M6 9v3h12V9 M12 12v5',
    integration_hub: 'M12 9a3 3 0 100 6 3 3 0 000-6z M12 3v6 M12 15v6 M3 12h6 M15 12h6',
    data_reports: 'M12 3v9h9 M20.5 14A9 9 0 119.5 3.5',
    access_management: 'M8 15a4 4 0 110-8 4 4 0 010 8z M11 11h10 M18 11v4 M21 11v3',
    administration: 'M4 6h10 M18 6h2 M4 12h4 M12 12h8 M4 18h12 M20 18h0 M16 4v4 M10 10v4 M18 16v4',
    home: 'M3 11l9-8 9 8 M5 10v11h14V10 M10 21v-6h4v6',
    profile: 'M12 11a4 4 0 100-8 4 4 0 000 8z M4 21c0-4 3.5-6 8-6s8 2 8 6'
  };
  var SUITE = { 'COMMAND': 'command_center', 'RISK': 'risk_register', 'CONTROLS & ASSURANCE': 'control_library_testing', 'EVENTS & FRAUD': 'incidents_losses', 'COMPLIANCE & PRIVACY': 'obligations_hub',
    'MANAGEMENT SYSTEMS': 'standards_hub', 'RESILIENCE': 'bcms_iso_22301', 'INTELLIGENCE': 'ai_insights', 'PLATFORM': 'integration_hub' };

  /* Bold, full-colour group icons for the menu (clear at a glance, like the EcoCash dashboard design). Gradients are defined once. */
  var GR = { g1: ['#3FA2FF', '#1556D6'], g2: ['#FFD54A', '#F59E0B'], g3: ['#2DD4BF', '#1E88E5'], g4: ['#FF6B6B', '#D91E2A'], g5: ['#A78BFA', '#6D3FE0'], g6: ['#4DA6FF', '#1D5FD0'], g7: ['#4ADE80', '#15A34A'], g8: ['#FDBA74', '#F26B0F'], g9: ['#5CB0FF', '#2563EB'] };
  function gear(cx, cy, ro, ri, n) { var pts = []; for (var i = 0; i < n * 2; i++) { var a = Math.PI * i / n - Math.PI / (2 * n), r = (i % 2 ? ri : ro); pts.push((cx + r * Math.cos(a)).toFixed(1) + ',' + (cy + r * Math.sin(a)).toFixed(1)); } return pts.join(' '); }
  var SOLID = {
    'COMMAND': '<rect x="3" y="3" width="11" height="11" rx="3" fill="url(#g1)"/><rect x="18" y="3" width="11" height="11" rx="3" fill="#FFFFFF" opacity=".95"/><rect x="3" y="18" width="11" height="11" rx="3" fill="#FFFFFF" opacity=".95"/><rect x="18" y="18" width="11" height="11" rx="3" fill="url(#g1)"/>',
    'RISK': '<path d="M16 2.5l11 4v8.5c0 7.2-4.6 12.2-11 14.5C9.6 27.2 5 22.2 5 15V6.5z" fill="url(#g2)"/><rect x="14.3" y="9" width="3.4" height="9" rx="1.7" fill="#5A3A00"/><circle cx="16" cy="22" r="2" fill="#5A3A00"/>',
    'CONTROLS & ASSURANCE': '<path d="M16 2.5l11 4v8.5c0 7.2-4.6 12.2-11 14.5C9.6 27.2 5 22.2 5 15V6.5z" fill="url(#g3)"/><path d="M10.5 15.5l4 4 7-8" fill="none" stroke="#fff" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"/>',
    'EVENTS & FRAUD': '<path d="M8 22v-7a8 8 0 0116 0v7z" fill="url(#g4)"/><rect x="5" y="22" width="22" height="5" rx="2" fill="#6B7A90"/><rect x="14.8" y="2" width="2.4" height="4" rx="1.2" fill="#FF8A8A"/><path d="M4.5 8.5l2.4 2.2M27.5 8.5l-2.4 2.2" stroke="#FF8A8A" stroke-width="2.2" stroke-linecap="round"/><path d="M12 15a4 4 0 014-4" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" opacity=".8"/>',
    'COMPLIANCE & PRIVACY': '<rect x="15" y="4" width="2.4" height="22" rx="1.2" fill="url(#g5)"/><rect x="8" y="26" width="16" height="3" rx="1.5" fill="url(#g5)"/><rect x="5" y="7" width="22" height="2.6" rx="1.3" fill="url(#g5)"/><path d="M3 18l3.5-8.5L10 18a3.5 3.5 0 01-7 0zM22 18l3.5-8.5L29 18a3.5 3.5 0 01-7 0z" fill="#C4B5FD"/>',
    'MANAGEMENT SYSTEMS': '<polygon points="' + gear(16, 16, 14, 10.5, 8) + '" fill="url(#g6)"/><circle cx="16" cy="16" r="5.2" fill="#fff"/><circle cx="16" cy="16" r="2.4" fill="#1D5FD0"/>',
    'RESILIENCE': '<path d="M1.5 17h6l3-9 5 18 4-12 2.5 3h8" fill="none" stroke="url(#g7)" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"/>',
    'INTELLIGENCE': '<circle cx="16" cy="16" r="13" fill="url(#g8)"/><path d="M16 7l2.3 6.7L25 16l-6.7 2.3L16 25l-2.3-6.7L7 16l6.7-2.3z" fill="#fff"/>',
    'PLATFORM': '<path d="M9 9l14 14M23 9L9 23" stroke="url(#g9)" stroke-width="3" stroke-linecap="round"/><circle cx="6.5" cy="6.5" r="4.2" fill="url(#g9)"/><circle cx="25.5" cy="6.5" r="4.2" fill="url(#g9)"/><circle cx="6.5" cy="25.5" r="4.2" fill="url(#g9)"/><circle cx="25.5" cy="25.5" r="4.2" fill="url(#g9)"/><rect x="12" y="12" width="8" height="8" rx="2.5" fill="#fff"/>'
  };
  SX.gradDefs = function () {
    return '<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs>' + Object.keys(GR).map(function (k) { return '<linearGradient id="' + k + '" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="' + GR[k][0] + '"/><stop offset="1" stop-color="' + GR[k][1] + '"/></linearGradient>'; }).join('') + '</defs></svg>';
  };
  SX.suiteIcon = function (name, size) { return '<svg class="sico" viewBox="0 0 32 32" width="' + (size || 28) + '" height="' + (size || 28) + '" aria-hidden="true">' + (SOLID[name] || SOLID.PLATFORM) + '</svg>'; };
  SX.iconPaths = P;
  /* line icon */
  SX.icon = function (key, size) {
    var d = P[key] || P[SUITE[key]] || P.command_center;
    return '<svg viewBox="0 0 24 24" width="' + (size || 18) + '" height="' + (size || 18) + '" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="' + d + '"/></svg>';
  };
  /* the glass tile used in the menu, the page banner and Home: a rounded square with the icon in it */
  SX.tile = function (key, size, color) {
    var s = size || 24;
    return '<span class="ico" style="--s:' + s + 'px;--c:' + (color || '#4DA3FF') + '">' + SX.icon(key, Math.round(s * 0.58)) + '</span>';
  };
})();
