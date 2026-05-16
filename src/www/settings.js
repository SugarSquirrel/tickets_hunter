
// action bar
const run_button = document.querySelector('#run_btn');
const save_button = document.querySelector('#save_btn');
const reset_button = document.querySelector('#reset_btn');
const exit_button = document.querySelector('#exit_btn');
const pause_button = document.querySelector('#pause_btn');
const resume_button = document.querySelector('#resume_btn');

// preference
const homepage = document.querySelector('#homepage');
const ticket_number = document.querySelector('#ticket_number');
const refresh_datetime = document.querySelector('#refresh_datetime');
const date_select_mode = document.querySelector('#date_select_mode');
const date_keyword = document.querySelector('#date_keyword');
const date_auto_fallback = document.querySelector('#date_auto_fallback');
const area_select_mode = document.querySelector('#area_select_mode');
const area_keyword = document.querySelector('#area_keyword');
const area_auto_fallback = document.querySelector('#area_auto_fallback');
const area_price_filter = document.querySelector('#area_price_filter');
const smart_sort_priority = document.querySelector('#smart_sort_priority');
const smart_sort_rank_direction = document.querySelector('#smart_sort_rank_direction');
const smart_sort_rank_n = document.querySelector('#smart_sort_rank_n');
const row_smart_sort_rank = document.querySelector('#row_smart_sort_rank');
const hint_smart_sort_rank = document.querySelector('#hint_smart_sort_rank');

// Show the direction + Nth-rank controls only when the priority dropdown
// is on "remaining rank". For "price high/low" / "random" the rank row
// would be meaningless so we collapse it.
function _toggle_smart_sort_rank_row() {
    if (!row_smart_sort_rank) return;
    const on = smart_sort_priority && smart_sort_priority.value === 'remaining rank';
    row_smart_sort_rank.style.display = on ? '' : 'none';
    if (hint_smart_sort_rank) hint_smart_sort_rank.style.display = on ? '' : 'none';
}
if (smart_sort_priority) {
    smart_sort_priority.addEventListener('change', _toggle_smart_sort_rank_row);
}

// Toggle visibility based on whether the user is in smart mode.
//   .smart-only         -> visible ONLY in smart mode
//   .legacy-mode-only   -> visible ONLY in the other (top/bottom/center/random) modes
function _toggle_smart_rows() {
    const show = (area_select_mode && area_select_mode.value === 'price range max remaining');
    document.querySelectorAll('.smart-only').forEach(function(el) {
        el.style.display = show ? '' : 'none';
    });
    document.querySelectorAll('.legacy-mode-only').forEach(function(el) {
        el.style.display = show ? 'none' : '';
    });
}
if (area_select_mode) {
    area_select_mode.addEventListener('change', _toggle_smart_rows);
}
const keyword_exclude = document.querySelector('#keyword_exclude');

// advance
const play_ticket_sound = document.querySelector('#play_ticket_sound');
const play_order_sound = document.querySelector('#play_order_sound');
const play_sound_filename = document.querySelector('#play_sound_filename');
const discord_webhook_url = document.querySelector('#discord_webhook_url');
const notification_message = document.querySelector('#notification_message');
const telegram_bot_token = document.querySelector('#telegram_bot_token');
const telegram_chat_id = document.querySelector('#telegram_chat_id');

const auto_press_next_step_button = document.querySelector('#auto_press_next_step_button');
const max_dwell_time = document.querySelector('#max_dwell_time');

const auto_reload_page_interval = document.querySelector('#auto_reload_page_interval');
const action_speed_multiplier = document.querySelector('#action_speed_multiplier');
const ocr_retry_cooldown = document.querySelector('#ocr_retry_cooldown');
const post_submit_reload_guard_seconds = document.querySelector('#post_submit_reload_guard_seconds');
const ticket_number_allow_max_fallback = document.querySelector('#ticket_number_allow_max_fallback');
const show_timing_log = document.querySelector('#show_timing_log');
const reset_browser_interval = document.querySelector('#reset_browser_interval');
const server_port = document.querySelector('#server_port');
const proxy_server_port = document.querySelector('#proxy_server_port');
const window_size = document.querySelector('#window_size');
const disable_adjacent_seat = document.querySelector('#disable_adjacent_seat');

const hide_some_image = document.querySelector('#hide_some_image');
const block_facebook_network = document.querySelector('#block_facebook_network');
const headless = document.querySelector('#headless');
const verbose = document.querySelector('#verbose');
const show_timestamp = document.querySelector('#show_timestamp');


const ocr_captcha_enable = document.querySelector('#ocr_captcha_enable');
const ocr_captcha_image_source = document.querySelector('#ocr_captcha_image_source');
const ocr_captcha_force_submit = document.querySelector('#ocr_captcha_force_submit');
const ocr_captcha_use_universal = document.querySelector('#ocr_captcha_use_universal');
const remote_url = document.querySelector('#remote_url');
const ocr_model_path = document.querySelector('#ocr_model_path');

// dictionary
const user_guess_string = document.querySelector('#user_guess_string');
const auto_guess_options = document.querySelector('#auto_guess_options');


// user info - personal data
const real_name = document.querySelector('#real_name');
const phone = document.querySelector('#phone');
const credit_card_prefix = document.querySelector('#credit_card_prefix');

// auto fill
const tixcraft_sid = document.querySelector('#tixcraft_sid');
const ibonqware = document.querySelector('#ibonqware');
const funone_session_cookie = document.querySelector('#funone_session_cookie');
const fansigo_cookie = document.querySelector('#fansigo_cookie');
const fansigo_account = document.querySelector('#fansigo_account');
const fansigo_password = document.querySelector('#fansigo_password');
const facebook_account = document.querySelector('#facebook_account');
const kktix_account = document.querySelector('#kktix_account');
const fami_account = document.querySelector('#fami_account');
const kham_account = document.querySelector('#kham_account');
const ticket_account = document.querySelector('#ticket_account');
const udn_account = document.querySelector('#udn_account');
const ticketplus_account = document.querySelector('#ticketplus_account');
const cityline_account = document.querySelector('#cityline_account');
const urbtix_account = document.querySelector('#urbtix_account');
const hkticketing_account = document.querySelector('#hkticketing_account');

const facebook_password = document.querySelector('#facebook_password');
const kktix_password = document.querySelector('#kktix_password');
const fami_password = document.querySelector('#fami_password');
const kham_password = document.querySelector('#kham_password');
const ticket_password = document.querySelector('#ticket_password');
const udn_password = document.querySelector('#udn_password');
const ticketplus_password = document.querySelector('#ticketplus_password');
const discount_code = document.querySelector('#discount_code');
const urbtix_password = document.querySelector('#urbtix_password');
const hkticketing_password = document.querySelector('#hkticketing_password');

// runtime
const idle_keyword = document.querySelector('#idle_keyword');
const resume_keyword = document.querySelector('#resume_keyword');
const idle_keyword_second = document.querySelector('#idle_keyword_second');
const resume_keyword_second = document.querySelector('#resume_keyword_second');
const dark_mode_toggle = document.querySelector('#dark_mode_toggle');
const theme_status = document.querySelector('#theme_status');

var settings = null;

maxbot_load_api();

// Keyword conversion functions (aligned with util.py logic)
function format_keyword_for_display(keyword_string) {
    // Convert JSON format to user display format
    // Input:  "AA BB","CC","DD"
    // Output: AA BB;CC;DD
    if (!keyword_string || keyword_string.length === 0) {
        return '';
    }

    // Replace "," or ',' with ";" or ';' (convert delimiter)
    keyword_string = keyword_string.replace(/","/g, '";').replace(/','/, "';");

    // Remove all quotes for display
    keyword_string = keyword_string.replace(/["']/g, '');

    return keyword_string;
}

function format_config_keyword_for_json(user_input) {
    // Convert user input to JSON format
    // Input:  AA BB;CC;DD
    // Output: "AA BB","CC","DD"
    if (!user_input || user_input.length === 0) {
        return '';
    }

    // Remove any existing quotes first
    user_input = user_input.replace(/["']/g, '');

    // Use semicolon as the ONLY delimiter (Issue #23)
    if (user_input.includes(';')) {
        const items = user_input.split(';')
            .map(item => item.trim())
            .filter(item => item.length > 0);
        return items.map(item => `"${item}"`).join(',');
    } else {
        return `"${user_input.trim()}"`;
    }
}

// Toggle Cityline login hint visibility based on account input
function updateCitylineHintVisibility() {
    const citylineHint = document.querySelector('#cityline-login-hint');
    if (citylineHint && cityline_account) {
        citylineHint.style.display = cityline_account.value.trim() !== '' ? '' : 'none';
    }
}

// Check if URL is Tixcraft family — delegates to PLATFORM_MAP as single source of truth
function isTixcraftFamily(url) {
    return detectPlatform(url) === 'tixcraft';
}

// Platform detection map
const PLATFORM_MAP = [
    { key: 'tixcraft',    domains: ['tixcraft.com', 'teamear.com', 'indievox.com', 'ticketmaster.'] },
    { key: 'kktix',       domains: ['kktix.com', 'kktix.cc'] },
    { key: 'ibon',        domains: ['ibon.com'] },
    { key: 'famiticket',  domains: ['famiticket.com'] },
    { key: 'kham',        domains: ['kham.com.tw'] },
    { key: 'ticket',      domains: ['ticket.com.tw'] },
    { key: 'udn',         domains: ['udnfunlife.com'] },
    { key: 'ticketplus',  domains: ['ticketplus.com'] },
    { key: 'cityline',    domains: ['cityline.com'] },
    { key: 'hkticketing', domains: ['hkticketing.com', 'galaxymacau.com', 'ticketek.com'] },
    { key: 'funone',      domains: ['funone.io'] },
    { key: 'fansigo',     domains: ['fansi.me'] },
    { key: 'urbtix',      domains: ['urbtix.hk'] },
];

function detectPlatform(url) {
    if (!url) return null;
    for (const platform of PLATFORM_MAP) {
        if (platform.domains.some(d => url.includes(d))) {
            return platform.key;
        }
    }
    return null;
}

let _lastPlatform = undefined;

function updatePlatformFields(url) {
    const platform = detectPlatform(url);
    if (platform === _lastPlatform) return;
    _lastPlatform = platform;
    const fields = $('[data-under]').addClass('disappear');
    if (platform) {
        fields.filter(`[data-under~="${platform}"]`).removeClass('disappear');
    }
    updateCitylineHintVisibility();
}

// Toggle Tixcraft refresh rate warning visibility
function updateTixcraftRefreshWarning() {
    const warningElement = document.getElementById('tixcraft-refresh-warning');
    if (!warningElement) return;

    const url = homepage.value;
    const interval = parseFloat(auto_reload_page_interval.value);

    // Show warning if: Tixcraft family site AND refresh interval < 8 seconds
    const shouldShowWarning = isTixcraftFamily(url) && !isNaN(interval) && interval > 0 && interval < 8;

    if (shouldShowWarning) {
        warningElement.style.display = 'block';
        setTimeout(() => {
            warningElement.classList.add('show');
        }, 10);
    } else {
        if (warningElement.classList.contains('show')) {
            warningElement.classList.remove('show');
            setTimeout(() => {
                warningElement.style.display = 'none';
            }, 150);
        }
    }
}

function load_settins_to_form(settings)
{
    if (settings)
    {
        //console.log("ticket_number:"+ settings.ticket_number);
        // preference
        homepage.value = settings.homepage;
        ticket_number.value = settings.ticket_number;
        refresh_datetime.value = settings.refresh_datetime;
        date_select_mode.value = settings.date_auto_select.mode;
        date_keyword.value = format_keyword_for_display(settings.date_auto_select.date_keyword);
        date_auto_fallback.checked = settings.date_auto_fallback || false;

        area_select_mode.value = settings.area_auto_select.mode;
        area_keyword.value = format_keyword_for_display(settings.area_auto_select.area_keyword);
        area_auto_fallback.checked = settings.area_auto_fallback || false;
        if (area_price_filter) area_price_filter.value = settings.area_auto_select.price_filter || '';
        if (smart_sort_priority) {
            const raw_priority = settings.area_auto_select.smart_sort_priority || 'remaining rank';
            // Legacy values that we silently fold into the new rank scheme so the
            // UI never shows an empty dropdown for older configs.
            if (raw_priority === 'max remaining') {
                smart_sort_priority.value = 'remaining rank';
                if (smart_sort_rank_direction) smart_sort_rank_direction.value = 'high';
                if (smart_sort_rank_n) smart_sort_rank_n.value = 1;
            } else if (raw_priority === 'min remaining') {
                smart_sort_priority.value = 'remaining rank';
                if (smart_sort_rank_direction) smart_sort_rank_direction.value = 'low';
                if (smart_sort_rank_n) smart_sort_rank_n.value = 1;
            } else {
                smart_sort_priority.value = raw_priority;
                if (smart_sort_rank_direction) smart_sort_rank_direction.value = settings.area_auto_select.smart_sort_rank_direction || 'high';
                if (smart_sort_rank_n) smart_sort_rank_n.value = settings.area_auto_select.smart_sort_rank_n || 1;
            }
        }
        _toggle_smart_rows();
        _toggle_smart_sort_rank_row();

        keyword_exclude.value = format_keyword_for_display(settings.keyword_exclude);
        
        // advanced

        play_ticket_sound.checked = settings.advanced.play_sound.ticket;
        play_order_sound.checked = settings.advanced.play_sound.order;
        play_sound_filename.value = settings.advanced.play_sound.filename;
        discord_webhook_url.value = settings.advanced.discord_webhook_url || '';
        notification_message.value = settings.advanced.discord_message || settings.advanced.telegram_message || '';
        telegram_bot_token.value = settings.advanced.telegram_bot_token || '';
        telegram_chat_id.value = settings.advanced.telegram_chat_id || '';

        auto_press_next_step_button.checked = settings.kktix.auto_press_next_step_button;
        max_dwell_time.value = settings.kktix.max_dwell_time;

        auto_reload_page_interval.value = settings.advanced.auto_reload_page_interval;
        if (action_speed_multiplier) {
            const mult = settings.advanced.action_speed_multiplier;
            action_speed_multiplier.value = (mult === undefined || mult === null) ? 1.0 : mult;
        }
        if (ocr_retry_cooldown) {
            const cool = settings.advanced.ocr_retry_cooldown;
            ocr_retry_cooldown.value = (cool === undefined || cool === null) ? 2.5 : cool;
        }
        if (post_submit_reload_guard_seconds) {
            const v = settings.advanced.post_submit_reload_guard_seconds;
            post_submit_reload_guard_seconds.value = (v === undefined || v === null) ? 180 : v;
        }
        if (ticket_number_allow_max_fallback) {
            const flag = settings.advanced.ticket_number_allow_max_fallback;
            ticket_number_allow_max_fallback.checked = (flag === undefined || flag === null) ? true : !!flag;
        }
        if (show_timing_log) {
            const flag = settings.advanced.show_timing_log;
            show_timing_log.checked = (flag === undefined || flag === null) ? true : !!flag;
        }
        reset_browser_interval.value = settings.advanced.reset_browser_interval;
        server_port.value = settings.advanced.server_port || 16888;
        proxy_server_port.value  = settings.advanced.proxy_server_port;
        window_size.value  = settings.advanced.window_size;

        disable_adjacent_seat.checked = settings.advanced.disable_adjacent_seat;

        hide_some_image.checked = settings.advanced.hide_some_image;
        block_facebook_network.checked = settings.advanced.block_facebook_network;
        headless.checked = settings.advanced.headless;
        verbose.checked = settings.advanced.verbose;
        show_timestamp.checked = settings.advanced.show_timestamp;


        ocr_captcha_enable.checked = settings.ocr_captcha.enable;
        ocr_captcha_image_source.value  = settings.ocr_captcha.image_source;
        ocr_captcha_force_submit.checked = settings.ocr_captcha.force_submit;

        if(settings.ocr_captcha.use_universal !== undefined) {
            ocr_captcha_use_universal.checked = settings.ocr_captcha.use_universal;
        } else {
            ocr_captcha_use_universal.checked = true;
        }

        let remote_url_string = "";
        let remote_url_array = [];
        if(settings.advanced.remote_url.length > 0) {
            remote_url_array = JSON.parse('[' +  settings.advanced.remote_url +']');
        }
        if(remote_url_array.length) {
            remote_url_string = remote_url_array[0];
        }
        remote_url.value = remote_url_string;

        // custom OCR model path
        if(settings.ocr_captcha.path) {
            ocr_model_path.value = settings.ocr_captcha.path;
        } else {
            ocr_model_path.value = "";
        }

        // dictionary
        user_guess_string.value = format_keyword_for_display(settings.advanced.user_guess_string);
        auto_guess_options.checked = settings.advanced.auto_guess_options;

        // contact info
        if (settings.contact) {
            real_name.value = settings.contact.real_name || '';
            phone.value = settings.contact.phone || '';
            credit_card_prefix.value = settings.contact.credit_card_prefix || '';
        }

        // auto fill (accounts section)
        tixcraft_sid.value = settings.accounts.tixcraft_sid;
        ibonqware.value = settings.accounts.ibonqware;
        funone_session_cookie.value = settings.accounts.funone_session_cookie || '';
        fansigo_cookie.value = settings.accounts.fansigo_cookie || '';
        fansigo_account.value = settings.accounts.fansigo_account || '';
        fansigo_password.value = settings.accounts.fansigo_password || '';
        facebook_account.value = settings.accounts.facebook_account;
        kktix_account.value = settings.accounts.kktix_account;
        fami_account.value = settings.accounts.fami_account;
        kham_account.value = settings.accounts.kham_account;
        ticket_account.value = settings.accounts.ticket_account;
        udn_account.value = settings.accounts.udn_account;
        ticketplus_account.value = settings.accounts.ticketplus_account;
        cityline_account.value = settings.accounts.cityline_account;
        urbtix_account.value = settings.accounts.urbtix_account;
        hkticketing_account.value = settings.accounts.hkticketing_account;

        facebook_password.value = settings.accounts.facebook_password;
        kktix_password.value = settings.accounts.kktix_password;
        fami_password.value = settings.accounts.fami_password;
        kham_password.value = settings.accounts.kham_password;
        ticket_password.value = settings.accounts.ticket_password;
        udn_password.value = settings.accounts.udn_password;
        ticketplus_password.value = settings.accounts.ticketplus_password;
        discount_code.value = settings.advanced.discount_code || '';
        urbtix_password.value = settings.accounts.urbtix_password;
        hkticketing_password.value = settings.accounts.hkticketing_password;

        // runtime
        idle_keyword.value = settings.advanced.idle_keyword;
        if(idle_keyword.value=='""') {
            idle_keyword.value='';
        }
        resume_keyword.value = settings.advanced.resume_keyword;
        if(resume_keyword.value=='""') {
            resume_keyword.value='';
        }
        idle_keyword_second.value = settings.advanced.idle_keyword_second;
        if(idle_keyword_second.value=='""') {
            idle_keyword_second.value='';
        } else if(idle_keyword_second.value && idle_keyword_second.value.includes('","')) {
            // 新增：簡化顯示格式 "00","30","50" → 00,30,50
            idle_keyword_second.value = idle_keyword_second.value.replace(/"/g, '');
        }
        resume_keyword_second.value = settings.advanced.resume_keyword_second;
        if(resume_keyword_second.value=='""') {
            resume_keyword_second.value='';
        } else if(resume_keyword_second.value && resume_keyword_second.value.includes('","')) {
            // 新增：簡化顯示格式
            resume_keyword_second.value = resume_keyword_second.value.replace(/"/g, '');
        }

        // Update platform-aware fields, Cityline hint, and Tixcraft warning after loading settings
        _lastPlatform = undefined;
        updatePlatformFields(homepage.value);
        updateTixcraftRefreshWarning();
    } else {
        console.log('no settings found');
    }
}

function maxbot_load_api()
{
    let api_url = "/load";
    $.get( api_url, function() {
        //alert( "success" );
    })
    .done(function(data) {
        //alert( "second success" );
        //console.log(data);
        settings = data;
        load_settins_to_form(data);
    })
    .fail(function() {
        //alert( "error" );
    })
    .always(function() {
        //alert( "finished" );
    });
}

function maxbot_reset_api()
{
    let api_url = "/reset";
    $.get( api_url, function() {
        //alert( "success" );
    })
    .done(function(data) {
        //alert( "second success" );
        //console.log(data);
        settings = data;
        load_settins_to_form(data);
        check_unsaved_fields();
        run_message("已重設為預設值");
    })
    .fail(function() {
        //alert( "error" );
    })
    .always(function() {
        //alert( "finished" );
    });
}

let messageClearTimer;

function message(msg)
{
    $("#message_detail").html("存檔完成");
    $("#message_modal").modal("show");
}

function message_old(msg)
{
    clearTimeout(messageClearTimer);
    const message = document.querySelector('#message');
    message.innerText = msg;
    messageClearTimer = setTimeout(function ()
        {
            message.innerText = '';
        }, 3000);
}

function maxbot_launch()
{
    run_message("啟動 MaxBot 主程式中...");
    save_changes_to_dict(true);
    maxbot_save_api(maxbot_run_api);
}

function maxbot_run_api()
{
    let api_url = "/run";
    $.get( api_url, function() {
        //alert( "success" );
    })
    .done(function(data) {
        run_message("啟動指令已發送，請稍候瀏覽器視窗開啟...");
        console.log("[MaxBot] Launch API response:", data);
    })
    .fail(function(xhr, status, error) {
        run_message("啟動失敗：無法連線到後端服務 (" + status + ")");
        console.error("[MaxBot] Launch API error:", status, error);
        console.error("[MaxBot] Response content:", xhr.responseText);
    })
    .always(function() {
        //alert( "finished" );
    });
}

function maxbot_shutdown_api()
{
    let api_url = "/shutdown";
    $.get( api_url, function() {
        //alert( "success" );
    })
    .done(function(data) {
        //alert( "second success" );
        window.close();
    })
    .fail(function() {
        //alert( "error" );
    })
    .always(function() {
        //alert( "finished" );
    });
}

function save_changes_to_dict(silent_flag)
{
    const ticket_number_value = parseInt(ticket_number.value);
    //console.log(ticket_number_value);
    if (!ticket_number_value)
    {
        message('提示: 請指定張數');
    } else {
        if(settings) {

            // preference
            settings.homepage = homepage.value;
            settings.ticket_number = ticket_number_value;
            settings.refresh_datetime = refresh_datetime.value;
            settings.date_auto_select.mode = date_select_mode.value;
            settings.date_auto_select.date_keyword = format_config_keyword_for_json(date_keyword.value);
            settings.date_auto_fallback = date_auto_fallback.checked;

            settings.area_auto_select.mode = area_select_mode.value;
            settings.area_auto_select.area_keyword = format_config_keyword_for_json(area_keyword.value);
            settings.area_auto_select.price_filter = area_price_filter ? area_price_filter.value.trim() : '';
            settings.area_auto_select.smart_sort_priority = smart_sort_priority ? smart_sort_priority.value : 'remaining rank';
            settings.area_auto_select.smart_sort_rank_direction = smart_sort_rank_direction ? smart_sort_rank_direction.value : 'high';
            const raw_n = smart_sort_rank_n ? parseInt(smart_sort_rank_n.value, 10) : 1;
            settings.area_auto_select.smart_sort_rank_n = (Number.isFinite(raw_n) && raw_n >= 1) ? raw_n : 1;
            // Drop deprecated keys so settings.json doesn't accumulate stale fields.
            delete settings.area_auto_select.price_min;
            delete settings.area_auto_select.price_max;
            settings.area_auto_fallback = area_auto_fallback.checked;

            settings.keyword_exclude = format_config_keyword_for_json(keyword_exclude.value);

            // advanced
            settings.advanced.play_sound.ticket = play_ticket_sound.checked;
            settings.advanced.play_sound.order = play_order_sound.checked;
            settings.advanced.play_sound.filename = play_sound_filename.value;
            settings.advanced.discord_webhook_url = discord_webhook_url.value;
            settings.advanced.discord_message = notification_message.value;
            settings.advanced.telegram_bot_token = telegram_bot_token.value;
            settings.advanced.telegram_chat_id = telegram_chat_id.value;
            settings.advanced.telegram_message = notification_message.value;

            settings.kktix.auto_press_next_step_button = auto_press_next_step_button.checked;
            settings.kktix.max_dwell_time = parseInt(max_dwell_time.value);

            settings.advanced.auto_reload_page_interval = Number(auto_reload_page_interval.value);
            if (action_speed_multiplier) {
                const raw = parseFloat(action_speed_multiplier.value);
                settings.advanced.action_speed_multiplier = (Number.isFinite(raw) && raw >= 0) ? raw : 1.0;
            }
            if (ocr_retry_cooldown) {
                const raw = parseFloat(ocr_retry_cooldown.value);
                settings.advanced.ocr_retry_cooldown = (Number.isFinite(raw) && raw >= 0 && raw <= 60) ? raw : 2.5;
            }
            if (post_submit_reload_guard_seconds) {
                const raw = parseFloat(post_submit_reload_guard_seconds.value);
                settings.advanced.post_submit_reload_guard_seconds = (Number.isFinite(raw) && raw >= 0 && raw <= 600) ? raw : 180.0;
            }
            if (ticket_number_allow_max_fallback) {
                settings.advanced.ticket_number_allow_max_fallback = !!ticket_number_allow_max_fallback.checked;
            }
            if (show_timing_log) {
                settings.advanced.show_timing_log = !!show_timing_log.checked;
            }
            settings.advanced.reset_browser_interval = parseInt(reset_browser_interval.value);
            settings.advanced.server_port = parseInt(server_port.value) || 16888;
            settings.advanced.proxy_server_port = proxy_server_port.value;
            settings.advanced.window_size = window_size.value;

            settings.advanced.disable_adjacent_seat = disable_adjacent_seat.checked;

            settings.advanced.hide_some_image = hide_some_image.checked;
            settings.advanced.block_facebook_network = block_facebook_network.checked;
            settings.advanced.headless = headless.checked;
            settings.advanced.verbose = verbose.checked;
            settings.advanced.show_timestamp = show_timestamp.checked;


            settings.ocr_captcha.enable = ocr_captcha_enable.checked;
            settings.ocr_captcha.image_source = ocr_captcha_image_source.value;
            settings.ocr_captcha.force_submit = ocr_captcha_force_submit.checked;
            settings.ocr_captcha.use_universal = ocr_captcha_use_universal.checked;

            let remote_url_array = [];
            remote_url_array.push(remote_url.value);
            let remote_url_string = JSON.stringify(remote_url_array);
            remote_url_string = remote_url_string.substring(0,remote_url_string.length-1);
            remote_url_string = remote_url_string.substring(1);
            //console.log("final remote_url_string:"+remote_url_string);
            settings.advanced.remote_url = remote_url_string;

            // custom OCR model path (migrated from advanced.ocr_model_path)
            settings.ocr_captcha.path = ocr_model_path.value;
            // Remove deprecated field if exists
            if (settings.advanced && settings.advanced.ocr_model_path !== undefined) {
                delete settings.advanced.ocr_model_path;
            }

            // dictionary
            settings.advanced.user_guess_string = format_config_keyword_for_json(user_guess_string.value);

            settings.advanced.auto_guess_options = auto_guess_options.checked;

            // contact info
            if (!settings.contact) settings.contact = {};
            settings.contact.real_name = real_name.value;
            settings.contact.phone = phone.value;
            settings.contact.credit_card_prefix = credit_card_prefix.value;

            // auto fill (accounts section)
            settings.accounts.tixcraft_sid = tixcraft_sid.value;
            settings.accounts.ibonqware = ibonqware.value;
            settings.accounts.funone_session_cookie = funone_session_cookie.value;
            settings.accounts.fansigo_cookie = fansigo_cookie.value;
            settings.accounts.fansigo_account = fansigo_account.value;
            settings.accounts.fansigo_password = fansigo_password.value;
            settings.accounts.facebook_account = facebook_account.value;
            settings.accounts.kktix_account = kktix_account.value;
            settings.accounts.fami_account = fami_account.value;
            settings.accounts.kham_account = kham_account.value;
            settings.accounts.ticket_account = ticket_account.value;
            settings.accounts.udn_account = udn_account.value;
            settings.accounts.ticketplus_account = ticketplus_account.value;
            settings.accounts.cityline_account = cityline_account.value;
            settings.accounts.urbtix_account = urbtix_account.value;
            settings.accounts.hkticketing_account = hkticketing_account.value;

            settings.accounts.facebook_password = facebook_password.value;
            settings.accounts.kktix_password = kktix_password.value;
            settings.accounts.fami_password = fami_password.value;
            settings.accounts.kham_password = kham_password.value;
            settings.accounts.ticket_password = ticket_password.value;
            settings.accounts.udn_password = udn_password.value;
            settings.accounts.ticketplus_password = ticketplus_password.value;
            settings.advanced.discount_code = discount_code.value;
            settings.accounts.urbtix_password = urbtix_password.value;
            settings.accounts.hkticketing_password = hkticketing_password.value;

            // runtime
            settings.advanced.idle_keyword = idle_keyword.value;
            settings.advanced.resume_keyword = resume_keyword.value;
            settings.advanced.idle_keyword_second = idle_keyword_second.value;
            settings.advanced.resume_keyword_second = resume_keyword_second.value;


        }
        if(!silent_flag) {
            message('已存檔');
        }
    }
}

function maxbot_save_api(callback)
{
    let api_url = "/save";
    if(settings) {
        $.post( api_url, JSON.stringify(settings), function() {
            //alert( "success" );
        })
        .done(function(data) {
            console.log("[MaxBot] 設定儲存成功");
            check_unsaved_fields();
            if(callback) callback();
        })
        .fail(function(xhr, status, error) {
            console.error("[MaxBot] Save API error:", status, error);
            console.error("[MaxBot] Response content:", xhr.responseText);
            run_message("儲存失敗：" + status);
        })
        .always(function() {
            //alert( "finished" );
        });
    }
}

function maxbot_pause_api()
{
    let api_url = "/pause";
    if(settings) {
        $.get( api_url, function() {
            //alert( "success" );
        })
        .done(function(data) {
            //alert( "second success" );
        })
        .fail(function() {
            //alert( "error" );
        })
        .always(function() {
            //alert( "finished" );
        });
    }
}

function maxbot_resume_api()
{
    let api_url = "/resume";
    if(settings) {
        $.get( api_url, function() {
            //alert( "success" );
        })
        .done(function(data) {
            //alert( "second success" );
        })
        .fail(function() {
            //alert( "error" );
        })
        .always(function() {
            //alert( "finished" );
        });
    }
}
function maxbot_save()
{
    run_message("儲存中...");
    save_changes_to_dict(true);  // silent mode - don't show modal
    maxbot_save_api(function() {
        run_message("已存檔");
    });
}

function check_unsaved_fields()
{
    if(settings) {
        const field_list_basic = ["homepage","ticket_number","refresh_datetime"];
        field_list_basic.forEach(f => {
            const field = document.querySelector('#'+f);
            if(field.value != settings[f]) {
                $("#"+f).addClass("is-invalid");
            } else {
                $("#"+f).removeClass("is-invalid");
            }
        });
        const field_list_accounts = [
            "tixcraft_sid",
            "ibonqware",
            "funone_session_cookie",
            "fansigo_cookie",
            "fansigo_account",
            "fansigo_password",
            "facebook_account",
            "kktix_account",
            "fami_account",
            "cityline_account",
            "urbtix_account",
            "hkticketing_account",
            "kham_account",
            "ticket_account",
            "udn_account",
            "ticketplus_account",
            "facebook_password",
            "kktix_password",
            "fami_password",
            "urbtix_password",
            "hkticketing_password",
            "kham_password",
            "ticket_password",
            "udn_password",
            "ticketplus_password"
        ];
        field_list_accounts.forEach(f => {
            const field = document.querySelector('#'+f);
            let formated_input = field.value;
            let formated_saved_value = settings["accounts"][f];
            if(typeof formated_saved_value == "string") {
                if(formated_input=='')
                    formated_input='""';
                if(formated_saved_value=='')
                    formated_saved_value='""';
                if(formated_saved_value.indexOf('"') > -1) {
                    if(formated_input.length) {
                        if(formated_input != '""') {
                            formated_input = '"' + formated_input + '"';
                        }
                    }
                }
            }
            let is_not_match = (formated_input != formated_saved_value);
            if(is_not_match) {
                $("#"+f).addClass("is-invalid");
            } else {
                $("#"+f).removeClass("is-invalid");
            }
        });
        const field_list_advance = [
            "user_guess_string",
            "remote_url",
            "auto_reload_page_interval",
            "reset_browser_interval",
            "proxy_server_port",
            "window_size",
            "idle_keyword",
            "resume_keyword",
            "idle_keyword_second",
            "resume_keyword_second",
            "discount_code"
        ];
        field_list_advance.forEach(f => {
            const field = document.querySelector('#'+f);
            let formated_input = field.value;
            let formated_saved_value = settings["advanced"][f];
            //console.log(f);
            //console.log(field.value);
            //console.log(formated_saved_value);
            if(typeof formated_saved_value == "string") {
                if(formated_input=='') 
                    formated_input='""';
                if(formated_saved_value=='') 
                    formated_saved_value='""';
                if(formated_saved_value.indexOf('"') > -1) {
                    if(formated_input.length) {
                        if(formated_input != '""') {
                            formated_input = '"' + formated_input + '"';
                        }
                    }
                }
            }
            let is_not_match = (formated_input != formated_saved_value);
            if(is_not_match) {
                //console.log(f);
                //console.log(formated_input);
                //console.log(formated_saved_value);
                $("#"+f).addClass("is-invalid");
            } else {
                $("#"+f).removeClass("is-invalid");
            }
        });

    }
}

function maxbot_status_api()
{
    let api_url = "/status";
    $.get( api_url, function() {
        //alert( "success" );
    })
    .done(function(data) {
        //alert( "second success" );
        // Pump the status badge up with size + padding so it's hard to miss.
        let status_text = "已暫停";
        let status_class = "badge text-bg-danger fs-5 px-3 py-2";
        if(data.status) {
            status_text="已啟動";
            status_class = "badge text-bg-success fs-5 px-3 py-2";
            $("#pause_btn").removeClass("disappear");
            $("#resume_btn").addClass("disappear");
            // Running -> hide the "press resume!" arrow.
            $("#resume_btn_arrow").addClass("disappear");
        } else {
            $("#pause_btn").addClass("disappear");
            $("#resume_btn").removeClass("disappear");
            // Paused -> surface the arrow that points at the resume button.
            $("#resume_btn_arrow").removeClass("disappear");
        }
        $("#last_url").text(data.last_url);
        $("#maxbot_status").html(status_text).prop( "class", status_class);
    })
    .fail(function() {
        //alert( "error" );
    })
    .always(function() {
        //alert( "finished" );
    });
}

function maxbot_version_api()
{
    let api_url = "/version";
    $.get( api_url, function() {
        //alert( "success" );
    })
    .done(function(data) {
        $("#maxbot_version").html(data.version);
    })
    .fail(function() {
        //alert( "error" );
    })
    .always(function() {
        //alert( "finished" );
    });
}

function update_system_time()
{
    var currentdate = new Date(); 
    var datetime = ("0" + currentdate.getHours()).slice(-2) + ":"  
                + ("0" + currentdate.getMinutes()).slice(-2) + ":" 
                + ("0" + currentdate.getSeconds()).slice(-2);
    $("#system_time").html(datetime);
}

var status_interval= setInterval(() => {
    maxbot_status_api();
    update_system_time();
}, 500);

maxbot_version_api();

run_button.addEventListener('click', maxbot_launch);
save_button.addEventListener('click', maxbot_save);
reset_button.addEventListener('click', maxbot_reset_api);
exit_button.addEventListener('click', maxbot_shutdown_api);
pause_button.addEventListener('click', maxbot_pause_api);
resume_button.addEventListener('click', maxbot_resume_api);

const onchange_tag_list = ["input","select","textarea"];
onchange_tag_list.forEach((tag) => {
    const input_items = document.querySelectorAll(tag);
    input_items.forEach((userItem) => {
        userItem.addEventListener('change', check_unsaved_fields);
    });
});

homepage.addEventListener('keyup', check_unsaved_fields);
homepage.addEventListener('input', () => updatePlatformFields(homepage.value));

ocr_captcha_use_universal.addEventListener('change', function() {
    if (this.checked) {
        ocr_model_path.value = 'assets/model/universal';
    } else {
        ocr_model_path.value = '';
    }
});

document.querySelector('#btn_test_discord_webhook').addEventListener('click', function() {
    const url = discord_webhook_url.value.trim();
    if (!url) {
        alert('Please enter Discord Webhook URL first.');
        return;
    }
    const btn = this;
    btn.disabled = true;
    btn.textContent = '...';
    $.ajax({
        url: '/test_discord_webhook',
        type: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({ webhook_url: url, custom_message: notification_message.value }),
        dataType: 'json'
    })
    .done(function(data) {
        if (data.success) {
            btn.className = 'btn btn-outline-success';
            btn.textContent = 'OK';
        } else {
            btn.className = 'btn btn-outline-danger';
            btn.textContent = 'Failed';
            alert('Test failed: ' + data.message);
        }
    })
    .fail(function() {
        btn.className = 'btn btn-outline-danger';
        btn.textContent = 'Error';
    })
    .always(function() {
        setTimeout(function() {
            btn.disabled = false;
            btn.textContent = '\u6E2C\u8A66';
            btn.className = 'btn btn-outline-secondary';
        }, 3000);
    });
});

document.querySelector('#btn_test_telegram').addEventListener('click', function() {
    const token = telegram_bot_token.value.trim();
    const chatId = telegram_chat_id.value.trim();
    if (!token || !chatId) {
        alert('Please enter both Telegram Bot Token and Chat ID first.');
        return;
    }
    const btn = this;
    btn.disabled = true;
    btn.textContent = '...';
    $.ajax({
        url: '/test_telegram',
        type: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({ bot_token: token, chat_id: chatId, custom_message: notification_message.value }),
        dataType: 'json'
    })
    .done(function(data) {
        if (data.success) {
            btn.className = 'btn btn-outline-success';
            btn.textContent = 'OK';
        } else {
            btn.className = 'btn btn-outline-danger';
            btn.textContent = 'Failed';
            alert('Test failed: ' + data.message);
        }
    })
    .fail(function() {
        btn.className = 'btn btn-outline-danger';
        btn.textContent = 'Error';
    })
    .always(function() {
        setTimeout(function() {
            btn.disabled = false;
            btn.textContent = '\u6E2C\u8A66';
            btn.className = 'btn btn-outline-secondary';
        }, 3000);
    });
});

let runMessageClearTimer;

function run_message(msg)
{
    clearTimeout(runMessageClearTimer);
    const message = document.querySelector('#run_btn_pressed_message');
    message.innerText = msg;
    runMessageClearTimer = setTimeout(function ()
        {
            message.innerText = '';
        }, 3000);
}

function home_tab_clicked() {
    document.getElementById("homepage").focus();
}

// Dark Mode Functions
function initTheme() {
    // Check if user has a saved preference
    const savedTheme = localStorage.getItem('theme');

    // If no saved preference, check system preference
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    const theme = savedTheme || (prefersDark ? 'dark' : 'light');

    // Apply theme
    applyTheme(theme);

    // Update toggle state
    dark_mode_toggle.checked = (theme === 'dark');
    updateThemeStatus(theme);
}

function applyTheme(theme) {
    document.documentElement.setAttribute('data-bs-theme', theme);
    localStorage.setItem('theme', theme);
}

function updateThemeStatus(theme) {
    // Update status badge if it exists (optional display element)
    if (theme_status) {
        if (theme === 'dark') {
            theme_status.textContent = '已啟用';
            theme_status.className = 'badge bg-success ms-2';
        } else {
            theme_status.textContent = '已關閉';
            theme_status.className = 'badge bg-secondary ms-2';
        }
    }
}

function toggleTheme() {
    const currentTheme = document.documentElement.getAttribute('data-bs-theme');
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';

    applyTheme(newTheme);
    updateThemeStatus(newTheme);
}

// Initialize theme on page load
initTheme();

// Add event listener for theme toggle
dark_mode_toggle.addEventListener('change', toggleTheme);

// ========================================
// Question Detection Feature
// ========================================

let questionCheckInterval = null;
let lastDetectedQuestion = '';

/**
 * Check if MAXBOT_QUESTION.txt exists and display the question
 */
async function checkDetectedQuestion() {
    try {
        const response = await fetch('/question');
        const data = await response.json();

        const alertElement = document.getElementById('detected-question-alert');
        const questionTextElement = document.getElementById('detected-question-text');

        if (data.exists && data.question) {
            // Only update if question content changed
            if (data.question !== lastDetectedQuestion) {
                lastDetectedQuestion = data.question;

                // Update question text
                questionTextElement.textContent = data.question;

                // Show alert with fade-in effect
                alertElement.style.display = 'block';
                setTimeout(() => {
                    alertElement.classList.add('show');
                }, 10);

                // Auto-scroll to the alert if verification tab is active
                const verificationTab = document.getElementById('verification-tab');
                if (verificationTab.classList.contains('active')) {
                    alertElement.scrollIntoView({ behavior: 'smooth', block: 'start' });
                }

                console.log('[QUESTION DETECTED]', data.question);
            }
        } else {
            // Hide alert if no question or file doesn't exist
            if (alertElement.classList.contains('show')) {
                alertElement.classList.remove('show');
                setTimeout(() => {
                    alertElement.style.display = 'none';
                }, 150);
                lastDetectedQuestion = '';
            }
        }
    } catch (error) {
        console.error('[QUESTION CHECK] Error:', error);
    }
}

/**
 * Start polling for question detection
 */
function startQuestionPolling() {
    // Check immediately
    checkDetectedQuestion();

    // Then check every 0.5 seconds
    if (!questionCheckInterval) {
        questionCheckInterval = setInterval(checkDetectedQuestion, 500);
        console.log('[QUESTION POLLING] Started (every 0.5 seconds)');
    }
}

/**
 * Stop polling
 */
function stopQuestionPolling() {
    if (questionCheckInterval) {
        clearInterval(questionCheckInterval);
        questionCheckInterval = null;
        console.log('[QUESTION POLLING] Stopped');
    }
}

// Start polling when page loads
startQuestionPolling();

// Cityline login hint visibility control
if (cityline_account) {
    cityline_account.addEventListener('input', updateCitylineHintVisibility);
}

// Tixcraft refresh warning visibility control
if (homepage) {
    homepage.addEventListener('input', updateTixcraftRefreshWarning);
    homepage.addEventListener('change', updateTixcraftRefreshWarning);
}
if (auto_reload_page_interval) {
    auto_reload_page_interval.addEventListener('input', updateTixcraftRefreshWarning);
    auto_reload_page_interval.addEventListener('change', updateTixcraftRefreshWarning);
}

// Also check when verification tab is clicked
const verificationTab = document.getElementById('verification-tab');
if (verificationTab) {
    verificationTab.addEventListener('click', () => {
        // Force check immediately when tab is clicked
        checkDetectedQuestion();
    });
}

// Search button handlers
async function searchQuestion(engine, event) {
    const questionText = document.getElementById('detected-question-text').textContent.trim();
    if (!questionText) {
        console.warn('[SEARCH] No question text available');
        return;
    }

    // AI prompt for direct answers
    const aiPrompt = "Answer this question directly in the same language as the question, provide only the answer without explanation:\n\n";

    // Determine if this is an AI service (needs prompt) or search engine (no prompt)
    const isAI = ['perplexity', 'chatgpt', 'grok', 'claude'].includes(engine);
    const fullQuestion = isAI ? aiPrompt + questionText : questionText;
    const encodedQuestion = encodeURIComponent(fullQuestion);

    let searchUrl = '';
    let needsCopy = false;

    switch (engine) {
        case 'google':
            searchUrl = `https://www.google.com/search?q=${encodeURIComponent(questionText)}`;
            break;
        case 'bing':
            searchUrl = `https://www.bing.com/search?q=${encodeURIComponent(questionText)}`;
            break;
        case 'perplexity':
            searchUrl = `https://www.perplexity.ai/?q=${encodedQuestion}`;
            break;
        case 'chatgpt':
            searchUrl = `https://chatgpt.com?q=${encodedQuestion}`;
            break;
        case 'claude':
            searchUrl = 'https://claude.ai/new';
            needsCopy = true;
            break;
        case 'grok':
            searchUrl = `https://grok.com?q=${encodedQuestion}`;
            break;
        default:
            console.error('[SEARCH] Unknown search engine:', engine);
            return;
    }

    // Check if Ctrl/Cmd/Middle-click (should open in background)
    const openInBackground = event && (event.ctrlKey || event.metaKey || event.button === 1);

    // For AI services, copy question to clipboard
    if (needsCopy) {
        try {
            await navigator.clipboard.writeText(fullQuestion);
            console.log(`[SEARCH] Question copied to clipboard for ${engine}`);

            // Only show notification if not opening in background
            if (!openInBackground) {
                const alertElement = document.getElementById('detected-question-alert');
                const originalText = alertElement.querySelector('h5').innerHTML;
                alertElement.querySelector('h5').innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" fill="currentColor" class="bi bi-check-circle-fill me-2" viewBox="0 0 16 16"><path d="M16 8A8 8 0 1 1 0 8a8 8 0 0 1 16 0m-3.97-3.03a.75.75 0 0 0-1.08.022L7.477 9.417 5.384 7.323a.75.75 0 0 0-1.06 1.06L6.97 11.03a.75.75 0 0 0 1.079-.02l3.992-4.99a.75.75 0 0 0-.01-1.05z"/></svg>問題已複製！請貼上到 ${engine.toUpperCase()}`;

                // Restore original text after 2 seconds
                setTimeout(() => {
                    alertElement.querySelector('h5').innerHTML = originalText;
                }, 2000);
            }
        } catch (err) {
            console.error('[SEARCH] Failed to copy to clipboard:', err);
            if (!openInBackground) {
                alert(`無法自動複製問題。請手動複製：\n\n${fullQuestion}`);
            }
        }
    }

    console.log(`[SEARCH] Opening ${engine}:`, searchUrl, openInBackground ? '(background)' : '(foreground)');

    // Open the URL
    // Note: window.open() behavior with Ctrl/Cmd is browser-dependent
    // Most modern browsers will open in background automatically when Ctrl/Cmd is pressed
    window.open(searchUrl, '_blank', 'noopener,noreferrer');
}

// Attach search button event listeners (pass event object)
document.getElementById('search-google-btn')?.addEventListener('click', (e) => searchQuestion('google', e));
document.getElementById('search-bing-btn')?.addEventListener('click', (e) => searchQuestion('bing', e));
document.getElementById('search-perplexity-btn')?.addEventListener('click', (e) => searchQuestion('perplexity', e));
document.getElementById('search-chatgpt-btn')?.addEventListener('click', (e) => searchQuestion('chatgpt', e));
document.getElementById('search-claude-btn')?.addEventListener('click', (e) => searchQuestion('claude', e));
document.getElementById('search-grok-btn')?.addEventListener('click', (e) => searchQuestion('grok', e));

// Also handle middle-click (button 1) for all search buttons
const searchButtons = [
    'search-google-btn', 'search-bing-btn', 'search-perplexity-btn',
    'search-chatgpt-btn', 'search-claude-btn', 'search-grok-btn'
];
searchButtons.forEach(btnId => {
    const btn = document.getElementById(btnId);
    const engine = btnId.replace('search-', '').replace('-btn', '');
    btn?.addEventListener('mousedown', (e) => {
        if (e.button === 1) { // Middle mouse button
            e.preventDefault();
            searchQuestion(engine, e);
        }
    });
});

// TixCraft SID validation
if (tixcraft_sid) {
    tixcraft_sid.addEventListener('input', () => {
        const warningElement = document.getElementById('tixcraft-sid-warning');
        const value = tixcraft_sid.value.trim();

        if (value.startsWith('g.')) {
            // Show warning with fade-in effect
            warningElement.style.display = 'block';
            setTimeout(() => {
                warningElement.classList.add('show');
            }, 10);
        } else {
            // Hide warning with fade-out effect
            if (warningElement.classList.contains('show')) {
                warningElement.classList.remove('show');
                setTimeout(() => {
                    warningElement.style.display = 'none';
                }, 150);
            }
        }
    });
}

// Help Panel — SVG icon injected from static constant (no user data)
const HELP_ICON_SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" class="bi bi-info-circle" viewBox="0 0 16 16"><path d="M8 15A7 7 0 1 1 8 1a7 7 0 0 1 0 14m0 1A8 8 0 1 0 8 0a8 8 0 0 0 0 16"/><path d="m8.93 6.588-2.29.287-.082.38.45.083c.294.07.352.176.288.469l-.738 3.468c-.194.897.105 1.319.808 1.319.545 0 1.178-.252 1.465-.598l.088-.416c-.2.176-.492.246-.686.246-.275 0-.375-.193-.304-.533zM9 4.5a1 1 0 1 1-2 0 1 1 0 0 1 2 0"/></svg>';
// Safe: HELP_ICON_SVG is a static developer-authored SVG string, not user input
document.querySelectorAll('.help-icon').forEach(function(el) { el.innerHTML = HELP_ICON_SVG; });
let currentHelpField = null;
let helpOffcanvasInstance = null;

function getHelpOffcanvas() {
    if (!helpOffcanvasInstance) {
        const el = document.getElementById('helpPanel');
        if (!el) return null;
        helpOffcanvasInstance = new bootstrap.Offcanvas(el);
        el.addEventListener('hide.bs.offcanvas', () => {
            currentHelpField = null;
        });
    }
    return helpOffcanvasInstance;
}

function buildHelpBody(content) {
    let html = '<div class="mb-3">' + content.detail + '</div>';
    if (content.faq && content.faq.length > 0) {
        html += '<div class="accordion accordion-flush" id="helpFaqAccordion">';
        content.faq.forEach(function(item, i) {
            html += '<div class="accordion-item">'
                + '<h2 class="accordion-header">'
                + '<button class="accordion-button collapsed py-2" type="button"'
                + ' data-bs-toggle="collapse" data-bs-target="#helpFaq' + i + '"'
                + ' aria-expanded="false">' + item.q + '</button>'
                + '</h2>'
                + '<div id="helpFaq' + i + '" class="accordion-collapse collapse"'
                + ' data-bs-parent="#helpFaqAccordion">'
                + '<div class="accordion-body py-2">' + item.a + '</div>'
                + '</div></div>';
        });
        html += '</div>';
    }
    return html;
}

function showHelp(fieldId) {
    var content = (typeof HELP_CONTENT !== 'undefined') && HELP_CONTENT[fieldId];
    if (!content) return;
    if (currentHelpField === fieldId) return;

    var oc = getHelpOffcanvas();
    if (!oc) return;

    currentHelpField = fieldId;
    document.getElementById('helpPanelTitle').textContent = content.title;
    // Safe: buildHelpBody returns static developer-authored HTML from help-content.js, no user input
    document.getElementById('helpPanelBody').innerHTML = buildHelpBody(content);

    var footer = document.getElementById('helpPanelFooter');
    var link = document.getElementById('helpPanelLink');
    if (content.link) {
        link.href = content.link;
        footer.style.display = '';
    } else {
        footer.style.display = 'none';
    }

    oc.show();
}

document.addEventListener('click', function(e) {
    var icon = e.target.closest('.help-icon');
    if (icon) {
        e.preventDefault();
        e.stopPropagation();
        showHelp(icon.dataset.help);
    }
});

document.addEventListener('keydown', function(e) {
    if ((e.key === 'Enter' || e.key === ' ') && e.target.classList.contains('help-icon')) {
        e.preventDefault();
        showHelp(e.target.dataset.help);
    }
});

// Clean up when page unloads
window.addEventListener('beforeunload', () => {
    stopQuestionPolling();
});


// ============================================================
// Bug 1.6-ⓘ Layer C: Manual reload-disable toggle (peak-load rescue)
// ============================================================
const noReloadToggleBtn = document.querySelector('#noReloadToggleBtn');
const noReloadStatusText = document.querySelector('#noReloadStatusText');

async function refreshNoReloadStatus() {
    if (!noReloadToggleBtn || !noReloadStatusText) return;
    try {
        const resp = await fetch('/api/no-reload');
        const data = await resp.json();
        if (data.active) {
            noReloadToggleBtn.textContent = '🔓 恢復 auto reload';
            noReloadToggleBtn.className = 'btn btn-danger';
            noReloadStatusText.textContent = '目前狀態：🔒 已暫停（bot 不會自動 reload）';
            noReloadStatusText.style.color = '#dc3545';
            noReloadStatusText.style.fontWeight = 'bold';
        } else {
            noReloadToggleBtn.textContent = '🔒 暫停 auto reload';
            noReloadToggleBtn.className = 'btn btn-warning';
            noReloadStatusText.textContent = '目前狀態：🔓 正常運作';
            noReloadStatusText.style.color = '';
            noReloadStatusText.style.fontWeight = 'normal';
        }
    } catch (e) {
        noReloadStatusText.textContent = '目前狀態：查詢失敗';
    }
}

if (noReloadToggleBtn) {
    noReloadToggleBtn.addEventListener('click', async () => {
        try {
            const formData = new FormData();
            formData.append('action', 'toggle');
            await fetch('/api/no-reload', { method: 'POST', body: formData });
            await refreshNoReloadStatus();
        } catch (e) {
            console.error('Failed to toggle no-reload marker:', e);
        }
    });
    refreshNoReloadStatus();
    setInterval(refreshNoReloadStatus, 5000);
}


// ============================================================
// Named presets (multi-account profiles)
// ============================================================
// Each preset is a full copy of settings.json saved under src/presets/{name}.json.
// "Save as..." copies the CURRENT settings.json after first persisting any
// unsaved form edits. "Load" overwrites settings.json with the chosen preset
// and reloads the page so all inputs reflect the new values.

const presets_dropdown      = document.querySelector('#presets_dropdown');
const btn_load_preset       = document.querySelector('#btn_load_preset');
const btn_save_preset       = document.querySelector('#btn_save_preset');
const btn_edit_preset       = document.querySelector('#btn_edit_preset');
const btn_delete_preset     = document.querySelector('#btn_delete_preset');
const presets_status        = document.querySelector('#presets_status');
const preset_edit_banner    = document.querySelector('#preset_edit_banner');
const preset_edit_name      = document.querySelector('#preset_edit_name');
const btn_save_to_preset    = document.querySelector('#btn_save_to_preset');
const btn_exit_edit_preset  = document.querySelector('#btn_exit_edit_preset');

// Name of the preset currently being edited in "decoupled" mode (form
// shows the preset, settings.json is left alone). Empty string when not
// in edit mode.
let _editing_preset_name = '';

function _set_save_button_warning(active) {
    const save_btn = document.querySelector('#save_btn');
    if (!save_btn) return;
    if (active) {
        save_btn.classList.add('btn-danger');
        save_btn.classList.remove('btn-primary');
        save_btn.dataset._origText = save_btn.dataset._origText || save_btn.textContent;
        save_btn.textContent = '⚠️ 存檔（會覆蓋 settings.json，影響搶票中）';
    } else {
        save_btn.classList.remove('btn-danger');
        save_btn.classList.add('btn-primary');
        if (save_btn.dataset._origText) {
            save_btn.textContent = save_btn.dataset._origText;
        }
    }
}

function _toggle_preset_main_buttons(disabled) {
    // Lock the buttons that write settings.json while we're editing a
    // non-active preset, so a misclick can't pollute the running bot.
    [btn_load_preset, btn_save_preset, btn_edit_preset, btn_delete_preset].forEach(function(btn) {
        if (!btn) return;
        btn.disabled = !!disabled;
        if (disabled) btn.classList.add('disabled');
        else btn.classList.remove('disabled');
    });
}

function _enter_edit_mode(name) {
    _editing_preset_name = name || '';
    if (preset_edit_banner) preset_edit_banner.style.display = _editing_preset_name ? '' : 'none';
    if (preset_edit_name)   preset_edit_name.textContent = _editing_preset_name;
    _set_save_button_warning(!!_editing_preset_name);
    _toggle_preset_main_buttons(!!_editing_preset_name);
}

function _exit_edit_mode() {
    _editing_preset_name = '';
    if (preset_edit_banner) preset_edit_banner.style.display = 'none';
    _set_save_button_warning(false);
    _toggle_preset_main_buttons(false);
}

function _presets_set_status(text, kind) {
    // kind: '', 'ok', 'err'
    if (!presets_status) return;
    presets_status.textContent = text || '';
    presets_status.classList.remove('text-success', 'text-danger', 'text-muted');
    if (kind === 'ok')       presets_status.classList.add('text-success');
    else if (kind === 'err') presets_status.classList.add('text-danger');
    else                     presets_status.classList.add('text-muted');
}

function _refresh_presets_dropdown(selected_name) {
    if (!presets_dropdown) return;
    $.ajax({
        url: '/presets/list',
        type: 'GET',
        dataType: 'json'
    }).done(function(data) {
        const names = (data && data.presets) ? data.presets : [];
        // Preserve placeholder, then append one option per preset.
        presets_dropdown.innerHTML = '<option value="">（請選擇）</option>';
        names.forEach(function(name) {
            const opt = document.createElement('option');
            opt.value = name;
            opt.textContent = name;
            presets_dropdown.appendChild(opt);
        });
        if (selected_name && names.indexOf(selected_name) !== -1) {
            presets_dropdown.value = selected_name;
        }
    }).fail(function(xhr, status, error) {
        console.error('[Presets] list failed:', status, error);
        _presets_set_status('讀取設定檔清單失敗', 'err');
    });
}

if (btn_save_preset) {
    btn_save_preset.addEventListener('click', function() {
        const name = window.prompt('輸入設定檔名稱（例如：帳號A、阿姨帳、媽媽帳）：', '');
        if (name === null) return;        // cancelled
        const cleaned = (name || '').trim();
        if (!cleaned) {
            _presets_set_status('名稱不能為空', 'err');
            return;
        }
        if (/[\/\\]|\.\./.test(cleaned) || cleaned.length > 64) {
            _presets_set_status('名稱不能包含 / \\ ..，最多 64 字', 'err');
            return;
        }
        // First flush any unsaved form edits to settings.json, then copy it.
        _presets_set_status('儲存中…', '');
        save_changes_to_dict(true);
        maxbot_save_api(function() {
            $.ajax({
                url: '/presets/save',
                type: 'POST',
                contentType: 'application/json',
                data: JSON.stringify({name: cleaned}),
                dataType: 'json'
            }).done(function(data) {
                if (data && data.success) {
                    _presets_set_status('已存為「' + cleaned + '」', 'ok');
                    _refresh_presets_dropdown(cleaned);
                } else {
                    _presets_set_status('存檔失敗：' + ((data && data.message) || '未知錯誤'), 'err');
                }
            }).fail(function(xhr, status, error) {
                _presets_set_status('存檔失敗：' + status, 'err');
            });
        });
    });
}

if (btn_load_preset) {
    btn_load_preset.addEventListener('click', function() {
        const name = presets_dropdown ? presets_dropdown.value : '';
        if (!name) {
            _presets_set_status('請先在下拉選擇設定檔', 'err');
            return;
        }
        const ok = window.confirm(
            '確定要載入「' + name + '」？\n\n' +
            '此操作會覆蓋目前的 settings.json，未存檔的修改會遺失。\n' +
            '載入完成後頁面會自動重新整理。'
        );
        if (!ok) return;
        _presets_set_status('載入中…', '');
        $.ajax({
            url: '/presets/load',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({name: name}),
            dataType: 'json'
        }).done(function(data) {
            if (data && data.success) {
                // Hard reload so every input rebinds from the new settings.json.
                window.location.reload();
            } else {
                _presets_set_status('載入失敗：' + ((data && data.message) || '未知錯誤'), 'err');
            }
        }).fail(function(xhr, status, error) {
            _presets_set_status('載入失敗：' + status, 'err');
        });
    });
}

// 「📝 編輯」: pull preset content into the form WITHOUT touching
// settings.json. The bot keeps running off the original config.
if (btn_edit_preset) {
    btn_edit_preset.addEventListener('click', function() {
        const name = presets_dropdown ? presets_dropdown.value : '';
        if (!name) {
            _presets_set_status('請先在下拉選擇要編輯的設定檔', 'err');
            return;
        }
        if (_editing_preset_name && _editing_preset_name !== name) {
            const ok = window.confirm(
                '已經在編輯「' + _editing_preset_name + '」。' +
                '切換到「' + name + '」會丟掉未存的修改，繼續嗎？'
            );
            if (!ok) return;
        }
        $.ajax({
            url: '/presets/get',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({name: name}),
            dataType: 'json'
        }).done(function(data) {
            if (data && data.success && data.config) {
                // Populate UI from the preset's config (NOT settings.json).
                settings = data.config;
                load_settins_to_form(data.config);
                _enter_edit_mode(name);
                _presets_set_status('已載入「' + name + '」到表單。settings.json 沒被動。', 'ok');
            } else {
                _presets_set_status('編輯載入失敗：' + ((data && data.message) || '未知錯誤'), 'err');
            }
        }).fail(function(xhr, status, error) {
            _presets_set_status('編輯載入失敗：' + status, 'err');
        });
    });
}

// 「💾 存到 preset」: write the form contents straight into the preset
// file. settings.json is left untouched so a running bot is unaffected.
if (btn_save_to_preset) {
    btn_save_to_preset.addEventListener('click', function() {
        if (!_editing_preset_name) {
            _presets_set_status('不在編輯模式，按這顆無效', 'err');
            return;
        }
        // Pull current form values into the `settings` global.
        save_changes_to_dict(true);
        $.ajax({
            url: '/presets/write_form',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({name: _editing_preset_name, config: settings}),
            dataType: 'json'
        }).done(function(data) {
            if (data && data.success) {
                _presets_set_status('已存到「' + _editing_preset_name + '」（settings.json 沒被動）', 'ok');
            } else {
                _presets_set_status('存到 preset 失敗：' + ((data && data.message) || '未知錯誤'), 'err');
            }
        }).fail(function(xhr, status, error) {
            _presets_set_status('存到 preset 失敗：' + status, 'err');
        });
    });
}

// 「✖ 結束編輯」: drop edit mode and refresh the form from the active
// settings.json so the user sees what the bot is actually running on.
if (btn_exit_edit_preset) {
    btn_exit_edit_preset.addEventListener('click', function() {
        _exit_edit_mode();
        maxbot_load_api();           // re-pulls settings.json into the form
        _presets_set_status('已結束編輯，表單已重新載入 settings.json', '');
    });
}

if (btn_delete_preset) {
    btn_delete_preset.addEventListener('click', function() {
        const name = presets_dropdown ? presets_dropdown.value : '';
        if (!name) {
            _presets_set_status('請先在下拉選擇設定檔', 'err');
            return;
        }
        const ok = window.confirm('確定要永久刪除「' + name + '」？此操作無法復原。');
        if (!ok) return;
        $.ajax({
            url: '/presets/delete',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({name: name}),
            dataType: 'json'
        }).done(function(data) {
            if (data && data.success) {
                _presets_set_status('已刪除「' + name + '」', 'ok');
                _refresh_presets_dropdown('');
            } else {
                _presets_set_status('刪除失敗：' + ((data && data.message) || '未知錯誤'), 'err');
            }
        }).fail(function(xhr, status, error) {
            _presets_set_status('刪除失敗：' + status, 'err');
        });
    });
}

// Populate the dropdown on initial load.
_refresh_presets_dropdown('');