class LogMessage {
    constructor(entry, toolNames) {
        const logLevel = this.determineLogLevel(entry.level);
        const safeMessage = this.escapeHtml(entry.message);
        const highlightedMessage = this.highlightToolNames(safeMessage, toolNames);

        const timestamp = new Date(entry.created * 1000).toLocaleTimeString();
        const metadataParts = [];
        if (entry.project_name) {
            metadataParts.push(`project: ${this.escapeHtml(entry.project_name)}`);
        }
        if (entry.session_id) {
            metadataParts.push(`session: ${this.escapeHtml(entry.session_id)}`);
        }
        const metadata = metadataParts.length > 0 ? `<span class="log-meta">${metadataParts.join(' \u2022 ')}</span>` : '';

        const header = `<div class="log-header"><span class="log-timestamp">${this.escapeHtml(timestamp)}</span>${metadata}</div>`;
        const body = `<div class="log-line">${highlightedMessage}</div>`;

        this.$elem = $('<div>').addClass('log-entry log-' + logLevel).html(header + body);
    }

    determineLogLevel(levelName) {
        const level = (levelName || '').toUpperCase();
        if (level === 'DEBUG') {
            return 'debug';
        } else if (level === 'INFO') {
            return 'info';
        } else if (level === 'WARNING' || level === 'WARN') {
            return 'warning';
        } else if (level === 'ERROR' || level === 'CRITICAL') {
            return 'error';
        } else {
            return 'default';
        }
    }

    highlightToolNames(message, toolNames) {
        let highlightedMessage = message;
        toolNames.forEach(function (toolName) {
            const escapedToolName = toolName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
            const regex = new RegExp('\\b' + escapedToolName + '\\b', 'gi');
            highlightedMessage = highlightedMessage.replace(regex, '<span class="tool-name">' + toolName + '</span>');
        });
        return highlightedMessage;
    }

    escapeHtml(convertString) {
        if (typeof convertString !== 'string') return convertString;

        const patterns = {
            '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;', '\'': '&#x27;', '`': '&#x60;'
        };

        return convertString.replace(/[<>&"'`]/g, match => patterns[match]);
    }
}

function updateThemeAwareImage($img, theme=null) {
    if (!theme) {
        const isDarkMode = $('html').data("theme") == 'dark';
        theme = isDarkMode ? 'dark' : 'light';
    }
    console.log("updating theme-aware image to theme:", theme);
    const newSrc = $img.data('src-' + theme);
    if (newSrc) {
        $img.attr('src', newSrc);
    }
}

/**
 * Manages banner loading, display, and navigation.
 */
class BannerRotation {
    constructor() {
        this.automaticRotationEnabled = false;

        this.platinumIndex = 0;
        this.goldIndex = 0;
        this.platinumTimer = null;
        this.goldTimer = null;
        this.platinumInterval = 15000;
        this.goldInterval = 15000;

        this.init();
    }

    init() {
        let self = this;
        this.loadBanners(function() {
            self.randomizeInitialBanner('platinum');
            self.randomizeInitialBanner('gold');

            if (self.automaticRotationEnabled) {
                self.startPlatinumRotation();
                self.startGoldRotation();
                $('.banner-arrow').hide();
            } else {
                self.hideArrowsIfSingle();
                self.bindArrowButtons();
            }
        });
    }

    loadBanners(onSuccess) {
        $.ajax({
            url: 'https://oraios-software.de/serena-banners/manifest.php',
            type: 'GET',
            success: function (response) {
                console.log('Banners loaded:', response);

                function fillBanners($container, banners, className) {
                    $.each(banners, function (index, banner) {
                        let $img = $('<img src="' + banner.image + '" alt="' + banner.alt + '" class="banner-image">');
                        if (banner.image_dark) {
                            $img.addClass('theme-aware-img');
                            $img.attr('data-src-dark', banner.image_dark);
                            $img.attr('data-src-light', banner.image);
                            updateThemeAwareImage($img);
                        }
                        let $anchor = $('<a href="' + banner.link + '" target="_blank"></a>');
                        $anchor.append($img);
                        let $banner = $('<div class="' + className + '-slide" data-banner="' + (index + 1) + '"></div>');
                        $banner.append($anchor);
                        if (index === 0) {
                            $banner.addClass('active');
                        }
                        if (banner.border) {
                            $img.addClass('banner-border');
                        }
                        $container.append($banner);
                    });
                }

                fillBanners($('#gold-banners'), response.gold, 'gold-banner');
                fillBanners($('#platinum-banners'), response.platinum, 'platinum-banner');
                onSuccess();
            },
            error: function (xhr, status, error) {
                console.error('Error loading banners:', error);
            }
        });
    }

    startPlatinumRotation() {
        const self = this;
        this.platinumTimer = setInterval(() => {
            self.rotatePlatinum('next');
        }, this.platinumInterval);
    }

    randomizeInitialBanner(type) {
        const slideClass = type === 'platinum' ? '.platinum-banner-slide' : '.gold-banner-slide';
        const $slides = $(slideClass);
        const total = $slides.length;

        if (total === 0) return;

        const randomIndex = Math.floor(Math.random() * total);
        if (type === 'platinum') {
            this.platinumIndex = randomIndex;
        } else {
            this.goldIndex = randomIndex;
        }
        $slides.removeClass('active');
        $slides.eq(randomIndex).addClass('active');
    }

    startGoldRotation() {
        const self = this;
        this.goldTimer = setInterval(() => {
            self.rotateGold('next');
        }, this.goldInterval);
    }

    hideArrowsIfSingle() {
        if ($('.platinum-banner-slide').length <= 1) {
            $('#platinum-banners .banner-arrow').hide();
        }
        if ($('.gold-banner-slide').length <= 1) {
            $('#gold-banners .banner-arrow').hide();
        }
    }

    bindArrowButtons() {
        let self = this;
        $('.banner-arrow').on('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            const target = $(this).data('target');
            const direction = $(this).hasClass('banner-arrow-right') ? 'next' : 'prev';
            if (target === 'platinum') {
                self.rotatePlatinum(direction);
            } else {
                self.rotateGold(direction);
            }
        });
    }

    rotatePlatinum(direction) {
        const $slides = $('.platinum-banner-slide');
        const total = $slides.length;

        if (total === 0) return;

        $slides.eq(this.platinumIndex).removeClass('active');

        if (direction === 'next') {
            this.platinumIndex = (this.platinumIndex + 1) % total;
        } else {
            this.platinumIndex = (this.platinumIndex - 1 + total) % total;
        }

        $slides.eq(this.platinumIndex).addClass('active');

        if (this.automaticRotationEnabled) {
            clearInterval(this.platinumTimer);
            this.startPlatinumRotation();
        }
    }

    rotateGold(direction) {
        const $groups = $('.gold-banner-slide');
        const total = $groups.length;

        if (total === 0) return;

        $groups.eq(this.goldIndex).removeClass('active');

        if (direction === 'next') {
            this.goldIndex = (this.goldIndex + 1) % total;
        } else {
            this.goldIndex = (this.goldIndex - 1 + total) % total;
        }

        $groups.eq(this.goldIndex).addClass('active');

        if (this.automaticRotationEnabled) {
            clearInterval(this.goldTimer);
            this.startGoldRotation();
        }
    }
}

class Dashboard {
    constructor() {
        let self = this;

        // Page state
        this.currentPage = 'overview';
        this.configData = null;
        this.lastConfigDataJson = null;
        this.jetbrainsMode = false;
        this.activeProjectName = null;
        this.languageToRemove = null;
        this.currentMemoryName = null;
        this.originalMemoryContent = null;
        this.memoryContentDirty = false;
        this.memoryToDelete = null;
        this.isAddingLanguage = false;
        this.waitingForConfigPollingResult = false;
        this.waitingForExecutionsPollingResult = false;
        this.originalSerenaConfigContent = null;
        this.serenaConfigContentDirty = false;

        // Execution tracking
        this.cancelledExecutions = [];
        this.executionToCancel = null;

        // Tool names and stats
        this.toolNames = [];
        this.activeSessions = [];
        this.logFilters = {
            projectName: '',
            sessionId: '',
            level: '',
        };
        this.currentMaxIdx = -1;
        this.pollInterval = null;
        this.configPollInterval = null;
        this.executionsPollInterval = null;
        this.activeProjectsPollInterval = null;
        this.heartbeatFailureCount = 0;

        // Chart references
        this.countChart = null;
        this.tokensChart = null;
        this.inputChart = null;
        this.outputChart = null;

        // Cache jQuery elements
        this.cacheElements();

        // Register event handlers
        this.bindEvents();

        // Initialize theme
        this.initializeTheme();

        // Initialize banner rotation
        this.bannerRotation = new BannerRotation();

        // Initialize the application
        this.loadToolNames().then(function () {
            self.loadNews();
            self.loadConfigOverview();
            self.startConfigPolling();
            self.startExecutionsPolling();
        });

        // Initialize heartbeat
        setInterval(this.heartbeat.bind(this), 250);
    }

    cacheElements() {
        this.$logContainer = $('#log-container');
        this.$errorContainer = $('#error-container');
        this.$saveLogsBtn = $('#save-logs-btn');
        this.$copyLogsBtn = $('#copy-logs-btn');
        this.$clearLogsBtn = $('#clear-logs-btn');
        this.$menuToggle = $('#menu-toggle');
        this.$menuDropdown = $('#menu-dropdown');
        this.$menuShutdown = $('#menu-shutdown');
        this.$themeToggle = $('#theme-toggle');
        this.$themeIcon = $('#theme-icon');
        this.$themeText = $('#theme-text');
        this.$configDisplay = $('#config-display');
        this.$basicStatsDisplay = $('#basic-stats-display');
        this.$refreshStats = $('#refresh-stats');
        this.$clearStats = $('#clear-stats');
        this.$projectsDisplay = $('#projects-display');
        this.$projectsHeader = $('#projects-header');
        this.$sessionsHeader = $('#sessions-header');
        this.$sessionsDisplay = $('#sessions-display');
        this.$availableToolsDisplay = $('#available-tools-display');
        this.$availableModesDisplay = $('#available-modes-display');
        this.$availableContextsDisplay = $('#available-contexts-display');
        this.$addLanguageModal = $('#add-language-modal');
        this.$modalLanguageSelect = $('#modal-language-select');
        this.$modalProjectName = $('#modal-project-name');
        this.$modalAddBtn = $('#modal-add-btn');
        this.$modalCancelBtn = $('#modal-cancel-btn');
        this.$removeLanguageModal = $('#remove-language-modal');
        this.$removeLanguageName = $('#remove-language-name');
        this.$removeModalOkBtn = $('#remove-modal-ok-btn');
        this.$removeModalCancelBtn = $('#remove-modal-cancel-btn');
        this.$editMemoryModal = $('#edit-memory-modal');
        this.$editMemoryName = $('#edit-memory-name');
        this.$editMemoryRenameBtn = $('#edit-memory-rename-btn');
        this.$editMemoryRenameInput = $('#edit-memory-rename-input');
        this.$editMemoryContent = $('#edit-memory-content');
        this.$editMemorySaveBtn = $('#edit-memory-save-btn');
        this.$editMemoryCancelBtn = $('#edit-memory-cancel-btn');
        this.$deleteMemoryModal = $('#delete-memory-modal');
        this.$deleteMemoryName = $('#delete-memory-name');
        this.$deleteMemoryOkBtn = $('#delete-memory-ok-btn');
        this.$deleteMemoryCancelBtn = $('#delete-memory-cancel-btn');
        this.$createMemoryModal = $('#create-memory-modal');
        this.$createMemoryProjectName = $('#create-memory-project-name');
        this.$createMemoryNameInput = $('#create-memory-name-input');
        this.$createMemoryCreateBtn = $('#create-memory-create-btn');
        this.$createMemoryCancelBtn = $('#create-memory-cancel-btn');
        this.$activeExecutionQueueDisplay = $('#active-executions-display');
        this.$lastExecutionDisplay = $('#last-execution-display');
        this.$cancelledExecutionsDisplay = $('#cancelled-executions-display');
        this.$cancelExecutionModal = $('#cancel-execution-modal');
        this.$cancelExecutionOkBtn = $('#cancel-execution-ok-btn');
        this.$cancelExecutionCancelBtn = $('#cancel-execution-cancel-btn');
        this.$editSerenaConfigModal = $('#edit-serena-config-modal');
        this.$editSerenaConfigContent = $('#edit-serena-config-content');
        this.$editSerenaConfigSaveBtn = $('#edit-serena-config-save-btn');
        this.$editSerenaConfigCancelBtn = $('#edit-serena-config-cancel-btn');
        this.$newsSection = $('#news-section');
        this.$newsDisplay = $('#news-display');
        this.$logProjectFilter = $('#log-project-filter');
        this.$logSessionFilter = $('#log-session-filter');
        this.$logLevelFilter = $('#log-level-filter');
        this.$logFilterReset = $('#log-filter-reset');
    }

    bindEvents() {
        let self = this;

        // Button handlers
        this.$saveLogsBtn.click(this.saveLogs.bind(this));
        this.$copyLogsBtn.click(this.copyLogs.bind(this));
        this.$clearLogsBtn.click(this.clearLogs.bind(this));
        this.$menuShutdown.click(function (e) {
            e.preventDefault();
            self.shutdown();
        });
        this.$menuToggle.click(this.toggleMenu.bind(this));
        this.$themeToggle.click(this.toggleTheme.bind(this));
        this.$refreshStats.click(this.loadStats.bind(this));
        this.$clearStats.click(this.clearStats.bind(this));

        // Modal handlers
        this.$modalAddBtn.click(this.addLanguageFromModal.bind(this));
        this.$modalCancelBtn.click(this.closeLanguageModal.bind(this));
        $('.modal-close').click(function() {
            const $modal = $(this).closest('.modal');
            if ($modal.is(self.$addLanguageModal)) self.closeLanguageModal();
            if ($modal.is(self.$removeLanguageModal)) self.closeRemoveLanguageModal();
            if ($modal.is(self.$editMemoryModal)) self.closeEditMemoryModal();
            if ($modal.is(self.$deleteMemoryModal)) self.closeDeleteMemoryModal();
            if ($modal.is(self.$createMemoryModal)) self.closeCreateMemoryModal();
            if ($modal.is(self.$cancelExecutionModal)) self.closeCancelExecutionModal();
            if ($modal.is(self.$editSerenaConfigModal)) self.closeEditSerenaConfigModal();
        });

        this.$removeModalOkBtn.click(this.confirmRemoveLanguageOk.bind(this));
        this.$removeModalCancelBtn.click(this.closeRemoveLanguageModal.bind(this));
        this.$editMemorySaveBtn.click(this.saveMemoryFromModal.bind(this));
        this.$editMemoryCancelBtn.click(this.closeEditMemoryModal.bind(this));
        this.$editMemoryContent.on('input', this.trackMemoryChanges.bind(this));
        this.$editMemoryRenameBtn.click(this.startMemoryRename.bind(this));
        this.$editMemoryRenameInput.keydown(function (e) {
            if (e.which === 13) {
                e.preventDefault();
                self.commitMemoryRename();
            } else if (e.which === 27) {
                e.preventDefault();
                self.cancelMemoryRename();
            }
        });
        this.$editMemoryRenameInput.on('blur', function () {
            self.cancelMemoryRename();
        });

        this.$logProjectFilter.on('change', () => {
            this.logFilters.projectName = this.$logProjectFilter.val() || '';
            this.loadLogs();
        });

        this.$logSessionFilter.on('change', () => {
            this.logFilters.sessionId = this.$logSessionFilter.val() || '';
            this.loadLogs();
        });

        this.$logLevelFilter.on('change', () => {
            this.logFilters.level = this.$logLevelFilter.val() || '';
            this.loadLogs();
        });

        this.$logFilterReset.click(() => {
            this.logFilters = { projectName: '', sessionId: '', level: '' };
            this.$logProjectFilter.val('');
            this.$logSessionFilter.val('');
            this.$logLevelFilter.val('');
            this.loadLogs();
        });
        this.$deleteMemoryOkBtn.click(this.confirmDeleteMemoryOk.bind(this));
        this.$deleteMemoryCancelBtn.click(this.closeDeleteMemoryModal.bind(this));
        this.$createMemoryCreateBtn.click(this.createMemoryFromModal.bind(this));
        this.$createMemoryCancelBtn.click(this.closeCreateMemoryModal.bind(this));
        this.$createMemoryNameInput.keypress(function (e) {
            if (e.which === 13) {
                e.preventDefault();
                self.createMemoryFromModal();
            }
        });
        this.$cancelExecutionOkBtn.click(this.confirmCancelExecutionOk.bind(this));
        this.$cancelExecutionCancelBtn.click(this.closeCancelExecutionModal.bind(this));
        this.$editSerenaConfigSaveBtn.click(this.saveSerenaConfigFromModal.bind(this));
        this.$editSerenaConfigCancelBtn.click(this.closeEditSerenaConfigModal.bind(this));

        // Page navigation
        $('[data-page]').click(function (e) {
            e.preventDefault();
            const page = $(this).data('page');
            self.navigateToPage(page);
        });

        // Close menu when clicking outside
        $(document).click(function (e) {
            if (!$(e.target).closest('.header-nav').length) {
                self.$menuDropdown.hide();
            }
        });

        // Close modals when clicking overlay
        $('.modal-overlay').click(function() {
            $(this).closest('.modal').find('.modal-close').trigger('click');
        });

        // Collapsible sections
        $('.collapsible-header').click(function () {
            const $header = $(this);
            const $content = $header.next('.collapsible-content');
            const $icon = $header.find('.toggle-icon');

            $content.slideToggle(200);
            $icon.toggleClass('expanded');
        });

        // ESC key handler
        $(document).keydown(function (e) {
            if (e.key === 'Escape' || e.keyCode === 27) {
                $('.modal:visible').each(function() {
                    $(this).find('.modal-close').trigger('click');
                });
            }
        });
    }

    heartbeat() {
        let self = this;
        $.ajax({
            url: '/heartbeat',
            type: 'GET',
            success: function (response) {
                self.heartbeatFailureCount = 0;
            },
            error: function (xhr, status, error) {
                self.heartbeatFailureCount++;
                console.error('Heartbeat failure; count = ', self.heartbeatFailureCount);
                if (self.heartbeatFailureCount >= 1) {
                    console.log('Server appears to be down, closing tab');
                    window.close();
                }
            },
        });
    }

    toggleMenu() {
        this.$menuDropdown.toggle();
    }

    navigateToPage(page) {
        // Hide menu
        this.$menuDropdown.hide();

        // Animate page transition
        const $currentPage = $('.page-view:visible');
        const $nextPage = $('#page-' + page);

        $currentPage.fadeOut(150, function() {
            $nextPage.fadeIn(200);
        });

        // Update menu active state
        $('[data-page]').removeClass('active');
        $('[data-page="' + page + '"]').addClass('active');

        // Update current page
        this.currentPage = page;

        // Stop all polling
        this.stopPolling();

        // Start appropriate polling for the page
        if (page === 'overview') {
            this.loadNews();
            this.startConfigPolling();
            this.startExecutionsPolling();
        } else if (page === 'active-projects') {
            this.loadActiveProjects();
            this.startActiveProjectsPolling();
        } else if (page === 'logs') {
            this.loadLogs();
        } else if (page === 'stats') {
            this.loadStats();
        }
    }

    stopPolling() {
        if (this.pollInterval) {
            clearInterval(this.pollInterval);
            this.pollInterval = null;
        }
        if (this.configPollInterval) {
            clearInterval(this.configPollInterval);
            this.configPollInterval = null;
        }
        if (this.executionsPollInterval) {
            clearInterval(this.executionsPollInterval);
            this.executionsPollInterval = null;
        }
        if (this.activeProjectsPollInterval) {
            clearInterval(this.activeProjectsPollInterval);
            this.activeProjectsPollInterval = null;
        }
    }

    // ===== Config Overview Methods =====

    loadConfigOverview() {
        if (this.waitingForConfigPollingResult) {
            console.log('Still waiting for previous config poll result, skipping this poll');
            return;
        }
        this.waitingForConfigPollingResult = true;
        console.log('Polling for config overview...');
        let self = this;
        $.ajax({
            url: '/get_config_overview',
            type: 'GET',
            success: function (response) {
                const currentConfigJson = JSON.stringify(response);
                const hasChanged = self.lastConfigDataJson !== currentConfigJson;

                if (hasChanged) {
                    console.log('Config has changed, updating display');
                    self.lastConfigDataJson = currentConfigJson;
                    self.configData = response;
                    self.jetbrainsMode = response.jetbrains_mode;
                    self.activeSessions = response.active_sessions || [];
                    self.updateLogFilterOptions(response);

                    // Set active project name - prefer new active_projects array, fallback to backward compat
                    const activeProjects = response.active_projects || [];
                    if (activeProjects.length > 0) {
                        // If we already have an active project name and it exists in the list, keep it
                        // Otherwise, default to the first project
                        const existingProject = activeProjects.find(p => p.name === self.activeProjectName);
                        if (!existingProject) {
                            self.activeProjectName = activeProjects[0].name;
                        }
                    } else {
                        // Fallback to backward compat single project
                        self.activeProjectName = response.active_project ? response.active_project.name : null;
                    }
                    
                    if (self.currentPage === 'overview') {
                        self.displayConfig(response);
                        self.displayBasicStats(response.tool_stats_summary || {});
                        self.displayProjects(response.registered_projects);
                        self.displayAvailableTools(response.available_tools);
                        self.displayAvailableModes(response.available_modes);
                        self.displayAvailableContexts(response.available_contexts);
                        self.displaySessions(self.activeSessions);
                    }
                    if (self.currentPage === 'active-projects') {
                        self.displayActiveProjects(response.active_projects || []);
                    }
                } else {
                    console.log('Config unchanged, skipping display update');
                }
            },
            error: function (xhr, status, error) {
                console.error('Error loading config overview:', error);
                if (self.currentPage === 'overview') {
                    self.showError(self.$configDisplay, 'Error loading configuration');
                    self.showError(self.$basicStatsDisplay, 'Error loading stats');
                    self.showError(self.$projectsDisplay, 'Error loading projects');
                }
                if (self.currentPage === 'active-projects') {
                    self.showError($('#active-projects-list'), 'Error loading active projects');
                }
            },
            complete: function () {
                self.waitingForConfigPollingResult = false;
            }
        });
    }

    showError($element, message) {
        $element.html('<div class="error-message">' + message + '</div>');
    }

    startConfigPolling() {
        this.loadConfigOverview();
        this.configPollInterval = setInterval(this.loadConfigOverview.bind(this), 1000);
    }

    startExecutionsPolling() {
        this.loadExecutions();
        this.executionsPollInterval = setInterval(() => {
            this.loadQueuedExecutions();
            this.loadLastExecution();
        }, 1000);
    }

    displayConfig(config) {
        try {
            const $existingToolsContent = $('#tools-content');
            const $existingMemoriesContent = $('#memories-content');
            const wasToolsExpanded = $existingToolsContent.is(':visible');
            const wasMemoriesExpanded = $existingMemoriesContent.is(':visible');

            // Get active projects array (new backend format) or fallback to single project
            const activeProjects = config.active_projects || [];
            
            // Determine which project to display details for
            let selectedProject = null;
            if (activeProjects.length > 0) {
                const foundProject = activeProjects.find(p => p.name === this.activeProjectName);
                selectedProject = foundProject || activeProjects[0];
                this.activeProjectName = selectedProject.name;
            } else {
                selectedProject = config.active_project;
                this.activeProjectName = config.active_project ? config.active_project.name : null;
            }

            let html = '';

            // Version badge
            $('#version-badge').text('v' + config.serena_version);

            // Active Projects Cards Section - show ALL active projects
            if (activeProjects.length > 0) {
                html += '<div class="active-projects-section">';
                html += '<h3 class="section-title"><span class="section-icon">📂</span> Active Projects (' + activeProjects.length + ')</h3>';
                html += '<div class="projects-grid">';
                activeProjects.forEach(function (project) {
                    const isSelected = project.name === (selectedProject && selectedProject.name);
                    const lspStatus = project.lsp_running ? 'Running' : 'Stopped';
                    const lspClass = project.lsp_running ? 'status-running' : 'status-stopped';
                    const idleText = project.idle_seconds !== null && project.idle_seconds !== undefined
                        ? self.formatIdleTime(project.idle_seconds)
                        : 'Active now';
                    const languagesDisplay = project.languages
                        ? (Array.isArray(project.languages) ? project.languages.join(', ') : project.languages)
                        : 'N/A';

                    html += '<div class="project-card' + (isSelected ? ' selected' : '') + '" data-project-name="' + project.name + '">';
                    html += '<div class="project-card-header">';
                    html += '<div class="project-card-name" title="' + self.escapeHtml(project.name) + '">' + self.escapeHtml(project.name) + '</div>';
                    html += '<div class="project-card-status ' + lspClass + '">' + lspStatus + '</div>';
                    html += '</div>';
                    html += '<div class="project-card-path" title="' + self.escapeHtml(project.path || '') + '">' + self.escapeHtml(project.path || 'N/A') + '</div>';
                    html += '<div class="project-card-details">';
                    html += '<div class="detail-row"><span class="detail-label">Languages</span><span class="detail-value">' + self.escapeHtml(languagesDisplay) + '</span></div>';
                    html += '<div class="detail-row"><span class="detail-label">Last Active</span><span class="detail-value">' + idleText + '</span></div>';
                    html += '<div class="detail-row"><span class="detail-label">Encoding</span><span class="detail-value">' + self.escapeHtml(project.encoding || 'N/A') + '</span></div>';
                    if (project.read_only) {
                        html += '<div class="detail-row"><span class="read-only-badge">Read-Only</span></div>';
                    }
                    html += '</div>';
                    html += '</div>';
                });
                html += '</div>';
                html += '</div>';
            } else {
                html += '<div class="empty-state-box"><span class="empty-icon large">📂</span><h3>No Active Projects</h3><p>Activate a project from your MCP client to see it here.</p></div>';
            }

            // Shared Configuration Section
            html += '<div class="shared-config-section">';
            html += '<h3 class="section-title"><span class="section-icon">⚙️</span> Shared Configuration</h3>';
            html += '<div class="config-grid">';

            // Context info (shared)
            html += '<div class="config-label">Context</div>';
            html += '<div class="config-value" title="' + config.context.path + '">' + config.context.name + '</div>';

            // Modes info (shared)
            html += '<div class="config-label">Active Modes</div>';
            html += '<div class="config-value">';
            if (config.modes.length > 0) {
                const modeSpans = config.modes.map(function (mode) {
                    return '<span title="' + mode.path + '">' + mode.name + '</span>';
                });
                html += modeSpans.join(', ');
            } else {
                html += 'None';
            }
            html += '</div>';

            html += '</div>';
            html += '</div>';

            // Active tools - collapsible (shared)
            html += '<div class="tools-section">';
            html += '<h3 class="collapsible-header" id="tools-header" style="font-size: 14px; margin: 0; cursor: pointer; display: flex; align-items: center; justify-content: space-between; padding: 10px 0; border-top: 1px solid var(--border-color);">';
            html += '<span style="font-weight: 600; color: var(--text-secondary);">Active Tools (' + config.active_tools.length + ')</span>';
            html += '<span class="toggle-icon' + (wasToolsExpanded ? ' expanded' : '') + '">';
            html += '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"></polyline></svg>';
            html += '</span>';
            html += '</h3>';
            html += '<div class="collapsible-content tools-grid" id="tools-content" style="' + (wasToolsExpanded ? '' : 'display:none;') + ' margin-top: 10px; padding-bottom: 10px;">';
            config.active_tools.forEach(function (tool) {
                html += '<div class="tool-item" title="' + tool + '">' + tool + '</div>';
            });
            html += '</div>';
            html += '</div>';

            // Configuration help link and edit config button
            html += '<div style="margin-top: 20px; padding-top: 16px; border-top: 1px solid var(--border-color); display: flex; gap: 10px; align-items: center;">';
            html += '<div style="flex: 1; padding: 12px; background: var(--bg-primary); border-radius: 8px; font-size: 13px; border: 1px solid var(--border-color);">';
            html += '<span style="color: var(--text-muted); margin-right: 6px;">📖</span>';
            html += '<a href="https://oraios.github.io/serena/02-usage/050_configuration.html" target="_blank" rel="noopener noreferrer">View Configuration Guide</a>';
            html += '</div>';
            html += '<button id="edit-serena-config-btn" class="btn btn-secondary" style="white-space: nowrap;">Edit Global Config</button>';
            html += '</div>';

            this.$configDisplay.html(html);

            // Attach event handlers
            const self = this;
            
            // Project card click handlers - set as selected for detail view
            $('.project-card').click(function () {
                const projectName = $(this).data('project-name');
                self.activeProjectName = projectName;
                self.displayConfig(self.configData);
            });

            $('#edit-serena-config-btn').click(this.openEditSerenaConfigModal.bind(this));

            $('#tools-header').click(function () {
                const $header = $(this);
                const $content = $('#tools-content');
                const $icon = $header.find('.toggle-icon');
                $content.slideToggle(200);
                $icon.toggleClass('expanded');
            });
        } catch (error) {
            console.error('Error in displayConfig:', error);
            this.showError(this.$configDisplay, 'Error displaying configuration: ' + error.message);
        }
    }

    displayBasicStats(stats) {
        if (Object.keys(stats).length === 0) {
            this.$basicStatsDisplay.html('<div class="empty-state"><span class="empty-icon">📊</span><span class="empty-text">No tool usage stats collected yet</span></div>');
            return;
        }

        const sortedTools = Object.keys(stats).sort((a, b) => {
            return stats[b].num_calls - stats[a].num_calls;
        });

        const maxCalls = Math.max(...sortedTools.map(tool => stats[tool].num_calls));

        let html = '';
        sortedTools.forEach(function (toolName) {
            const count = stats[toolName].num_calls;
            const percentage = maxCalls > 0 ? (count / maxCalls * 100) : 0;

            html += '<div class="stat-bar-container">';
            html += '<div class="stat-tool-name" title="' + toolName + '">' + toolName + '</div>';
            html += '<div class="bar-wrapper">';
            html += '<div class="bar" style="width: ' + percentage + '%"></div>';
            html += '</div>';
            html += '<div class="stat-count">' + count + '</div>';
            html += '</div>';
        });

        this.$basicStatsDisplay.html(html);
    }

    displayProjects(projects) {
        if (!projects || projects.length === 0) {
            this.$projectsDisplay.html('<div class="empty-state small"><span class="empty-text">No projects registered</span></div>');
            return;
        }

        let html = '';
        projects.forEach(function (project) {
            const activeClass = project.is_active ? ' active' : '';
            html += '<div class="project-item' + activeClass + '">';
            html += '<div class="project-name" title="' + project.name + '">' + project.name + '</div>';
            html += '<div class="project-path" title="' + project.path + '">' + project.path + '</div>';
            html += '</div>';
        });

        this.$projectsDisplay.html(html);
    }

    populateSelectOptions($select, placeholder, items, selectedValue) {
        if (!$select || $select.length === 0) return;
        const currentValue = selectedValue || '';
        $select.empty();
        $select.append($('<option>').val('').text(placeholder));
        items.forEach(item => {
            if (!item) return;
            const value = typeof item === 'string' ? item : item.value;
            const label = typeof item === 'string' ? item : item.label;
            $select.append($('<option>').val(value).text(label));
        });
        $select.val(currentValue);
    }

    updateLogFilterOptions(config) {
        if (!this.$logProjectFilter || !this.$logSessionFilter) return;
        const projectNames = new Set();
        (config.active_projects || []).forEach(project => {
            if (project && project.name) {
                projectNames.add(project.name);
            }
        });
        const sortedProjects = Array.from(projectNames).sort();
        if (!sortedProjects.includes(this.logFilters.projectName)) {
            this.logFilters.projectName = '';
        }
        this.populateSelectOptions(this.$logProjectFilter, 'All projects', sortedProjects, this.logFilters.projectName);
        this.logFilters.projectName = this.$logProjectFilter.val() || '';

        const sessions = config.active_sessions || [];
        const sessionOptions = sessions.map(session => {
            const parts = [session.session_id];
            if (session.project_name) parts.push(`– ${session.project_name}`);
            if (session.client_info) parts.push(`(${session.client_info})`);
            return { value: session.session_id, label: parts.join(' ') };
        });
        if (!sessionOptions.some(option => option.value === this.logFilters.sessionId)) {
            this.logFilters.sessionId = '';
        }
        this.populateSelectOptions(this.$logSessionFilter, 'All sessions', sessionOptions, this.logFilters.sessionId);
        this.logFilters.sessionId = this.$logSessionFilter.val() || '';
    }

    displaySessions(sessions) {
        if (!this.$sessionsDisplay || this.$sessionsDisplay.length === 0) return;
        if (!sessions || sessions.length === 0) {
            this.$sessionsDisplay.html('<div class="empty-state small"><span class="empty-text">No active sessions</span></div>');
            return;
        }

        let html = '<div class="session-list">';
        sessions.forEach(session => {
            const projectName = session.project_name || 'Unbound';
            const idle = this.formatIdleTime(session.idle_seconds || 0);
            const client = session.client_info || 'Unknown client';
            const tags = [];
            if (session.context_name) tags.push(`context: ${session.context_name}`);
            if (session.persona_name) tags.push(`persona: ${session.persona_name}`);
            if (session.backend_hint) tags.push(`backend: ${session.backend_hint}`);

            html += '<div class="session-item">';
            html += `<div class="session-id" title="${this.escapeHtml(session.session_id)}">${this.escapeHtml(session.session_id)}</div>`;
            html += '<div class="session-meta">';
            html += `<span>Project: ${this.escapeHtml(projectName)}</span>`;
            html += `<span>Idle: ${this.escapeHtml(idle)}</span>`;
            html += `<span>Client: ${this.escapeHtml(client)}</span>`;
            html += '</div>';
            if (tags.length > 0) {
                html += '<div class="session-tags">'
                    + tags.map(tag => `<span class="session-tag">${this.escapeHtml(tag)}</span>`).join('')
                    + '</div>';
            }
            html += '</div>';
        });
        html += '</div>';

        this.$sessionsDisplay.html(html);
    }

    // ===== Active Projects Methods =====

    loadActiveProjects() {
        let self = this;
        $.ajax({
            url: '/get_config_overview',
            type: 'GET',
            success: function (response) {
                self.displayActiveProjects(response.active_projects || []);
            },
            error: function (xhr, status, error) {
                console.error('Error loading active projects:', error);
                $('#active-projects-list').html('<div class="error-message">Error loading active projects</div>');
            }
        });
    }

    startActiveProjectsPolling() {
        this.loadActiveProjects();
        this.activeProjectsPollInterval = setInterval(() => {
            this.loadActiveProjects();
        }, 2000);
    }

    displayActiveProjects(projects) {
        const $container = $('#active-projects-list');
        if (!projects || projects.length === 0) {
            $container.html('<div class="empty-state-box"><span class="empty-icon large">📂</span><h3>No Active Projects</h3><p>Activate a project from your MCP client to see it here.</p></div>');
            return;
        }

        let html = '';
        const self = this;

        projects.forEach(function (project) {
            const lspStatus = project.lsp_running ? 'Running' : 'Stopped';
            const lspClass = project.lsp_running ? 'status-running' : 'status-stopped';
            const cardClass = project.lsp_running ? '' : ' status-stopped';
            const idleText = project.idle_seconds !== null && project.idle_seconds !== undefined
                ? self.formatIdleTime(project.idle_seconds)
                : 'Active now';

            html += '<div class="active-project-card' + cardClass + '">';
            html += '<div class="active-project-header">';
            html += '<div class="active-project-name" title="' + self.escapeHtml(project.name || 'Unknown') + '">' + self.escapeHtml(project.name || 'Unknown') + '</div>';
            html += '<div class="active-project-status ' + lspClass + '">' + lspStatus + '</div>';
            html += '</div>';
            html += '<div class="active-project-path" title="' + self.escapeHtml(project.path || '') + '">' + self.escapeHtml(project.path || 'N/A') + '</div>';
            html += '<div class="active-project-details">';
            const languagesDisplay = project.languages
                ? (Array.isArray(project.languages) ? project.languages.join(', ') : project.languages)
                : 'N/A';
            html += '<div class="detail-row"><span class="detail-label">Languages</span><span class="detail-value">' + self.escapeHtml(languagesDisplay) + '</span></div>';
            html += '<div class="detail-row"><span class="detail-label">Last Active</span><span class="detail-value">' + idleText + '</span></div>';
            html += '</div>';
            html += '</div>';
        });

        $container.html(html);
    }

    formatIdleTime(seconds) {
        if (seconds === null || seconds === undefined) return 'Unknown';
        if (seconds < 60) return Math.floor(seconds) + 's ago';
        if (seconds < 3600) return Math.floor(seconds / 60) + 'm ago';
        return Math.floor(seconds / 3600) + 'h ' + Math.floor((seconds % 3600) / 60) + 'm ago';
    }

    displayAvailableTools(tools) {
        if (!tools || tools.length === 0) {
            this.$availableToolsDisplay.html('<div class="empty-state small"><span class="empty-text">All tools are active</span></div>');
            return;
        }

        let html = '';
        tools.forEach(function (tool) {
            html += '<div class="info-item" title="' + tool.name + '">' + tool.name + '</div>';
        });

        this.$availableToolsDisplay.html(html);
    }

    displayAvailableModes(modes) {
        if (!modes || modes.length === 0) {
            this.$availableModesDisplay.html('<div class="empty-state small"><span class="empty-text">No modes available</span></div>');
            return;
        }

        let html = '';
        modes.forEach(function (mode) {
            const activeClass = mode.is_active ? ' active' : '';
            html += '<div class="info-item' + activeClass + '" title="' + mode.path + '">' + mode.name + '</div>';
        });

        this.$availableModesDisplay.html(html);
    }

    displayAvailableContexts(contexts) {
        if (!contexts || contexts.length === 0) {
            this.$availableContextsDisplay.html('<div class="empty-state small"><span class="empty-text">No contexts available</span></div>');
            return;
        }

        let html = '';
        contexts.forEach(function (context) {
            const activeClass = context.is_active ? ' active' : '';
            html += '<div class="info-item' + activeClass + '" title="' + context.path + '">' + context.name + '</div>';
        });

        this.$availableContextsDisplay.html(html);
    }

    // ===== Executions Methods =====

    loadQueuedExecutions(onComplete) {
        let self = this;
        $.ajax({
            url: '/queued_task_executions',
            type: 'GET',
            success: function (response) {
                if (response.status === 'success') {
                    self.displayActiveExecutionsQueue(response.queued_executions || []);
                } else {
                    console.error('Error loading executions:', response.message);
                }
            },
            error: function (xhr, status, error) {
                console.error('Error loading executions:', error);
                self.$activeExecutionQueueDisplay.html('<div class="error-message">Error loading executions</div>');
            },
            complete: onComplete
        });
    }

    loadLastExecution(onComplete) {
        let self = this;
        $.ajax({
            url: '/last_execution',
            type: 'GET',
            success: function (response) {
                if (response.status === 'success') {
                    if (response.last_execution !== null && response.last_execution.logged) {
                        self.displayLastExecution(response.last_execution);
                    }
                } else {
                    console.error('Error loading last execution:', response.message);
                }
            },
            error: function (xhr, status, error) {
                console.error('Error loading last execution:', error);
                self.$lastExecutionDisplay.html('<div class="error-message">Error loading last execution</div>');
            },
            complete: onComplete
        });
    }

    loadExecutions() {
        const self = this;
        if (this.waitingForExecutionsPollingResult) {
            console.log('Still waiting for previous executions poll result, skipping this poll');
            return;
        }
        this.waitingForExecutionsPollingResult = true;
        console.log('Polling for executions...');
        const self = this;
        Promise.all([
            new Promise(resolve => { self.loadQueuedExecutions(); resolve(); }),
            new Promise(resolve => { self.loadLastExecution(); resolve(); })
        ]).finally(() => {
            self.waitingForExecutionsPollingResult = false;
        });
    }

    displayActiveExecutionsQueue(executions) {
        if (!executions || executions.length === 0) {
            this.$activeExecutionQueueDisplay.html('<div class="empty-state"><span class="empty-icon">✓</span><span class="empty-text">No pending tasks</span></div>');
            return;
        }

        let html = '<div class="execution-list">';
        let self = this;

        executions.forEach(function (execution) {
            const isRunning = execution.is_running;
            const logged = execution.logged;

            if (!logged) return;

            let itemClass = 'execution-item';
            if (isRunning) {
                itemClass += ' running';
            }

            const executionJson = JSON.stringify(execution).replace(/'/g, '&#39;');

            html += '<div class="' + itemClass + '" data-task-id="' + execution.task_id + '" data-execution=\'' + executionJson + '\'>';

            if (isRunning) {
                html += '<div class="execution-spinner"></div>';
            } else {
                html += '<div style="width: 14px; height: 14px; border-radius: 50%; background: var(--border-color); flex-shrink: 0;"></div>';
            }

            html += '<div class="execution-name" title="' + self.escapeHtml(execution.name) + '">' + self.escapeHtml(execution.name) + '</div>';

            if (isRunning) {
                html += '<div class="execution-meta">#' + execution.task_id + '</div>';
            } else {
                html += '<div class="execution-meta">queued · #' + execution.task_id + '</div>';
            }

            html += '<button class="execution-cancel-btn" data-task-id="' + execution.task_id + '" title="Cancel">&times;</button>';
            html += '</div>';
        });

        html += '</div>';
        this.$activeExecutionQueueDisplay.html(html);

        $('.execution-cancel-btn').click(function (e) {
            e.preventDefault();
            const $item = $(this).closest('.execution-item');
            const executionDataStr = $item.attr('data-execution');
            if (executionDataStr) {
                const unescapedStr = executionDataStr.replace(/&#39;/g, "'");
                const executionData = JSON.parse(unescapedStr);
                self.confirmCancelExecution(executionData);
            }
        });

        this.displayCancelledExecutions(executions);
    }

    displayLastExecution(execution) {
        if (!execution) {
            this.$lastExecutionDisplay.html('<div class="empty-state"><span class="empty-icon">-</span><span class="empty-text">No recent executions</span></div>');
            return;
        }

        const isSuccess = execution.finished_successfully;
        let html = '<div class="last-execution-container' + (isSuccess ? '' : ' error') + '">';

        html += '<div class="last-execution-icon-container">';
        html += isSuccess ? '&#10003;' : '&#10007;';
        html += '</div>';

        html += '<div class="last-execution-body">';
        html += '<div class="last-execution-status">' + (isSuccess ? 'Succeeded' : 'Failed') + '</div>';
        html += '<div class="last-execution-name" title="' + this.escapeHtml(execution.name) + '">' + this.escapeHtml(execution.name) + '</div>';
        html += '</div>';

        html += '<div class="execution-meta">#' + execution.task_id + '</div>';
        html += '</div>';

        this.$lastExecutionDisplay.html(html);
    }

    displayCancelledExecutions() {
        let self = this;
        const cancelledExecs = self.cancelledExecutions;

        if (cancelledExecs.length === 0) {
            $('.executions-section').eq(2).hide();
            return;
        }

        $('.executions-section').eq(2).show();

        let html = '<div class="execution-list">';

        cancelledExecs.forEach(function (execution) {
            const isAbandoned = execution.is_running;

            html += '<div class="execution-item ' + (isAbandoned ? 'abandoned' : 'cancelled') + '">';
            html += '<div class="execution-icon ' + (isAbandoned ? 'abandoned' : 'cancelled') + '">';
            html += isAbandoned ? '!' : '&#10007;';
            html += '</div>';
            html += '<div class="execution-name">' + self.escapeHtml(execution.name) + '</div>';
            html += '<div class="execution-meta">' + (isAbandoned ? 'abandoned · ' : '') + '#' + execution.task_id + '</div>';
            html += '</div>';
        });

        html += '</div>';
        this.$cancelledExecutionsDisplay.html(html);
    }

    confirmCancelExecution(executionData) {
        console.log('confirmCancelExecution called with:', executionData);
        this.executionToCancel = executionData;

        if (executionData.is_running) {
            console.log('Showing modal for running execution');
            this.$cancelExecutionModal.fadeIn(200);
        } else {
            console.log('Directly cancelling queued execution');
            this.cancelExecution(executionData);
        }
    }

    confirmCancelExecutionOk() {
        if (this.executionToCancel) {
            this.cancelExecution(this.executionToCancel);
        }
        this.closeCancelExecutionModal();
    }

    cancelExecution(executionData) {
        const self = this;

        console.log('cancelExecution called with:', executionData);

        $.ajax({
            url: '/cancel_task_execution',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ task_id: executionData.task_id }),
            success: function (response) {
                console.log('Cancel task response:', response);

                if (response.status === 'error') {
                    console.error('Backend returned error status:', response.message);
                    alert('Error cancelling task: ' + response.message);
                    return;
                }

                if (response.status === 'success') {
                    if (response.was_cancelled) {
                        const alreadyCancelled = self.cancelledExecutions.some(function (exec) {
                            return exec.task_id === executionData.task_id;
                        });
                        if (!alreadyCancelled) {
                            self.cancelledExecutions.push(executionData);
                        }
                    }
                    self.loadQueuedExecutions();
                } else {
                    alert('Unexpected response from server');
                }
            },
            error: function (xhr, status, error) {
                console.error('AJAX error cancelling task:', error);
                let errorMessage = error;
                if (xhr.responseJSON && xhr.responseJSON.message) {
                    errorMessage = xhr.responseJSON.message;
                }
                alert('Error cancelling task: ' + errorMessage);
            }
        });
    }

    closeCancelExecutionModal() {
        this.$cancelExecutionModal.fadeOut(200);
        this.executionToCancel = null;
    }

    escapeHtml(text) {
        if (typeof text !== 'string') return text;

        const patterns = {
            '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;', "'": '&#x27;', '`': '&#x60;'
        };

        return text.replace(/[<>&"'`]/g, match => patterns[match]);
    }

    // ===== Logs Methods =====

    getLogRequestPayload(startIdx) {
        const payload = { start_idx: startIdx };
        if (this.logFilters.projectName) {
            payload.project_name = this.logFilters.projectName;
        }
        if (this.logFilters.sessionId) {
            payload.session_id = this.logFilters.sessionId;
        }
        if (this.logFilters.level) {
            payload.levels = [this.logFilters.level];
        }
        return payload;
    }

    displayLogMessage(entry) {
        this.$logContainer.append(new LogMessage(entry, this.toolNames).$elem);
    }

    loadToolNames() {
        let self = this;
        return $.ajax({
            url: '/get_tool_names',
            type: 'GET',
            success: function (response) {
                self.toolNames = response.tool_names || [];
                console.log('Loaded tool names:', self.toolNames);
            },
            error: function (xhr, status, error) {
                console.error('Error loading tool names:', error);
            }
        });
    }

    updateTitle(activeProject) {
        const projectName = typeof activeProject === 'object' && activeProject !== null ? activeProject.name : activeProject;
        document.title = projectName ? `${projectName} – Serena Dashboard` : 'Serena Dashboard';
    }

    updateLogButtons(hasLogs) {
        this.$saveLogsBtn.prop('disabled', !hasLogs);
        this.$copyLogsBtn.prop('disabled', !hasLogs);
        this.$clearLogsBtn.prop('disabled', !hasLogs);
    }

    saveLogs() {
        const logText = this.$logContainer.text();
        const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
        const blob = new Blob([logText], {type: 'text/plain'});
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `serena-logs-${timestamp}.txt`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);

        const originalHtml = this.$saveLogsBtn.html();
        const checkmarkSvg = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#22c55e" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg><span>Saved!</span>';
        this.$saveLogsBtn.html(checkmarkSvg);
        setTimeout(() => { this.$saveLogsBtn.html(originalHtml); }, 1500);
    }

    copyLogs() {
        const logText = this.$logContainer.text();
        navigator.clipboard.writeText(logText).then(() => {
            const originalHtml = this.$copyLogsBtn.html();
            const checkmarkSvg = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#22c55e" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg><span>Copied!</span>';
            this.$copyLogsBtn.html(checkmarkSvg);
            setTimeout(() => {
                this.$copyLogsBtn.html(originalHtml);
            }, 1500);
        }).catch(err => {
            console.error('Failed to copy logs:', err);
        });
    }

    clearLogs() {
        let self = this;
        $.ajax({
            url: '/clear_logs',
            type: 'POST',
            success: function () {
                self.$logContainer.empty();
                self.currentMaxIdx = -1;
                self.updateLogButtons(false);

                const originalHtml = self.$clearLogsBtn.html();
                const checkmarkSvg = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#22c55e" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg><span>Cleared!</span>';
                self.$clearLogsBtn.html(checkmarkSvg);
                setTimeout(() => { self.$clearLogsBtn.html(originalHtml); }, 1500);
            },
            error: function (xhr, status, error) {
                console.error('Failed to clear logs:', error);
            }
        });
    }

    loadLogs() {
        console.log("Loading logs");
        let self = this;

        self.$errorContainer.empty();

        if (self.pollInterval) {
            clearInterval(self.pollInterval);
            self.pollInterval = null;
        }

        self.currentMaxIdx = -1;

        $.ajax({
            url: '/get_log_messages',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify(self.getLogRequestPayload(0)),
            success: function (response) {
                self.$logContainer.empty();
                self.currentMaxIdx = response.max_idx || -1;

                if (response.messages && response.messages.length > 0) {
                    response.messages.forEach(function (message) {
                        self.displayLogMessage(message);
                    });

                    const logContainer = $('#log-container')[0];
                    logContainer.scrollTop = logContainer.scrollHeight;
                } else {
                    $('#log-container').html('<div class="empty-state"><span class="empty-icon">📝</span><span class="empty-text">No log messages found</span></div>');
                }

                self.updateLogButtons(response.messages && response.messages.length > 0);
                self.updateTitle(response.active_project);
                self.startPeriodicPolling();
            },
            error: function (xhr, status, error) {
                console.error('Error loading logs:', error);
                self.$errorContainer.html('<div class="error-message">Error loading logs: ' + (xhr.responseJSON ? xhr.responseJSON.detail : error) + '</div>');
            }
        });
    }

    pollForNewLogs() {
        let self = this;
        console.log("Polling logs", this.currentMaxIdx);
        $.ajax({
            url: '/get_log_messages',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify(self.getLogRequestPayload(self.currentMaxIdx + 1)),
            success: function (response) {
                if (response.messages && response.messages.length > 0) {
                    let wasAtBottom = false;
                    const logContainer = $('#log-container')[0];

                    if (logContainer.scrollHeight > 0) {
                        wasAtBottom = (logContainer.scrollTop + logContainer.clientHeight) >= (logContainer.scrollHeight - 10);
                    }

                    response.messages.forEach(function (message) {
                        self.displayLogMessage(message);
                    });

                    self.currentMaxIdx = response.max_idx || self.currentMaxIdx;
                    self.updateLogButtons(true);

                    if (wasAtBottom) {
                        logContainer.scrollTop = logContainer.scrollHeight;
                    }
                } else {
                    self.currentMaxIdx = response.max_idx || self.currentMaxIdx;
                }

                self.updateTitle(response.active_project);
            }
        });
    }

    startPeriodicPolling() {
        if (this.pollInterval) {
            clearInterval(this.pollInterval);
        }
        this.pollInterval = setInterval(this.pollForNewLogs.bind(this), 1000);
    }

    // ===== Stats Methods =====

    loadStats() {
        let self = this;
        $.when(
            $.ajax({ url: '/get_tool_stats', type: 'GET' }),
            $.ajax({ url: '/get_token_count_estimator_name', type: 'GET' })
        ).done(function (statsResp, estimatorResp) {
            const stats = statsResp[0].stats;
            const tokenCountEstimatorName = estimatorResp[0].token_count_estimator_name;
            self.displayStats(stats, tokenCountEstimatorName);
        }).fail(function () {
            console.error('Error loading stats or estimator name');
        });
    }

    clearStats() {
        let self = this;
        $.ajax({
            url: '/clear_tool_stats',
            type: 'POST',
            success: function () {
                self.loadStats();
            },
            error: function (xhr, status, error) {
                console.error('Error clearing stats:', error);
            }
        });
    }

    displayStats(stats, tokenCountEstimatorName) {
        const names = Object.keys(stats);
        if (names.length === 0) {
            $('#stats-summary').hide();
            $('#estimator-name').hide();
            $('.charts-container').hide();
            $('#no-stats-message').show();
            return;
        }

        $('#estimator-name').show();
        $('#stats-summary').show();
        $('.charts-container').show();
        $('#no-stats-message').hide();

        $('#estimator-name').html('<strong>Token estimator:</strong> ' + tokenCountEstimatorName);

        const counts = names.map(n => stats[n].num_times_called);
        const inputTokens = names.map(n => stats[n].input_tokens);
        const outputTokens = names.map(n => stats[n].output_tokens);
        const totalTokens = names.map(n => stats[n].input_tokens + stats[n].output_tokens);

        const totalCalls = counts.reduce((sum, count) => sum + count, 0);
        const totalInputTokens = inputTokens.reduce((sum, tokens) => sum + tokens, 0);
        const totalOutputTokens = outputTokens.reduce((sum, tokens) => sum + tokens, 0);

        const colors = this.generateColors(names.length);

        const countCtx = document.getElementById('count-chart');
        const tokensCtx = document.getElementById('tokens-chart');
        const inputCtx = document.getElementById('input-chart');
        const outputCtx = document.getElementById('output-chart');

        if (this.countChart) this.countChart.destroy();
        if (this.tokensChart) this.tokensChart.destroy();
        if (this.inputChart) this.inputChart.destroy();
        if (this.outputChart) this.outputChart.destroy();

        this.updateSummaryTable(totalCalls, totalInputTokens, totalOutputTokens);

        Chart.register(ChartDataLabels);

        const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
        const textColor = isDark ? '#f7fafc' : '#1a1d23';
        const gridColor = isDark ? '#2d3748' : '#e2e8f0';

        this.countChart = new Chart(countCtx, {
            type: 'pie',
            data: {
                labels: names,
                datasets: [{ data: counts, backgroundColor: colors }]
            },
            options: {
                plugins: {
                    legend: { display: true, labels: { color: textColor } },
                    datalabels: { display: true, color: 'white', font: { weight: 'bold' }, formatter: (value) => value }
                }
            }
        });

        this.inputChart = new Chart(inputCtx, {
            type: 'pie',
            data: {
                labels: names,
                datasets: [{ data: inputTokens, backgroundColor: colors }]
            },
            options: {
                plugins: {
                    legend: { display: true, labels: { color: textColor } },
                    datalabels: { display: true, color: 'white', font: { weight: 'bold' }, formatter: (value) => value }
                }
            }
        });

        this.outputChart = new Chart(outputCtx, {
            type: 'pie',
            data: {
                labels: names,
                datasets: [{ data: outputTokens, backgroundColor: colors }]
            },
            options: {
                plugins: {
                    legend: { display: true, labels: { color: textColor } },
                    datalabels: { display: true, color: 'white', font: { weight: 'bold' }, formatter: (value) => value }
                }
            }
        });

        this.tokensChart = new Chart(tokensCtx, {
            type: 'bar',
            data: {
                labels: names,
                datasets: [
                    { label: 'Input Tokens', data: inputTokens, backgroundColor: colors.map(color => color + '80'), borderColor: colors, borderWidth: 2, borderSkipped: false, yAxisID: 'y' },
                    { label: 'Output Tokens', data: outputTokens, backgroundColor: colors, yAxisID: 'y1' }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { labels: { color: textColor } }
                },
                scales: {
                    x: { ticks: { color: textColor }, grid: { color: gridColor } },
                    y: { type: 'linear', display: true, position: 'left', beginAtZero: true, title: { display: true, text: 'Input Tokens', color: textColor }, ticks: { color: textColor }, grid: { color: gridColor } },
                    y1: { type: 'linear', display: true, position: 'right', beginAtZero: true, title: { display: true, text: 'Output Tokens', color: textColor }, ticks: { color: textColor }, grid: { drawOnChartArea: false, color: gridColor } }
                }
            }
        });
    }

    generateColors(count) {
        const colors = ['#e88d3c', '#6366f1', '#22c55e', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4', '#ec4899', '#84cc16', '#f97316'];
        return Array.from({length: count}, (_, i) => colors[i % colors.length]);
    }

    updateSummaryTable(totalCalls, totalInputTokens, totalOutputTokens) {
        const tableHtml = `
            <table class="stats-summary">
                <tr><th>Metric</th><th>Total</th></tr>
                <tr><td>Tool Calls</td><td>${totalCalls}</td></tr>
                <tr><td>Input Tokens</td><td>${totalInputTokens.toLocaleString()}</td></tr>
                <tr><td>Output Tokens</td><td>${totalOutputTokens.toLocaleString()}</td></tr>
                <tr><td>Total Tokens</td><td>${(totalInputTokens + totalOutputTokens).toLocaleString()}</td></tr>
            </table>
        `;
        $('#stats-summary').html(tableHtml);
    }

    // ===== Theme Methods =====

    initializeTheme() {
        const savedTheme = localStorage.getItem('serena-theme');

        if (savedTheme) {
            this.setTheme(savedTheme);
        } else {
            this.detectSystemTheme();
        }

        this.setupSystemThemeListener();
    }

    detectSystemTheme() {
        const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
        const theme = prefersDark ? 'dark' : 'light';
        this.setTheme(theme);
    }

    setupSystemThemeListener() {
        const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');

        const handleSystemThemeChange = (e) => {
            const savedTheme = localStorage.getItem('serena-theme');
            if (!savedTheme) {
                const newTheme = e.matches ? 'dark' : 'light';
                this.setTheme(newTheme);
            }
        };

        if (mediaQuery.addEventListener) {
            mediaQuery.addEventListener('change', handleSystemThemeChange);
        } else {
            mediaQuery.addListener(handleSystemThemeChange);
        }
    }

    toggleTheme() {
        const currentTheme = document.documentElement.getAttribute('data-theme') || 'light';
        const newTheme = currentTheme === 'light' ? 'dark' : 'light';
        localStorage.setItem('serena-theme', newTheme);
        this.setTheme(newTheme);
    }

    setTheme(theme) {
        document.documentElement.setAttribute('data-theme', theme);

        if (theme === 'dark') {
            this.$themeIcon.text('☀️');
            this.$themeText.text('Light');
        } else {
            this.$themeIcon.text('🌙');
            this.$themeText.text('Dark');
        }

        $(".theme-aware-img").each(function() {
            const $img = $(this);
            updateThemeAwareImage($img, theme);
        });

        localStorage.setItem('serena-theme', theme);
        this.updateChartsTheme();
    }

    updateChartsTheme() {
        const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
        const textColor = isDark ? '#f7fafc' : '#1a1d23';
        const gridColor = isDark ? '#2d3748' : '#e2e8f0';

        if (this.countChart && this.countChart.options.plugins) {
            if (this.countChart.options.plugins.legend) {
                this.countChart.options.plugins.legend.labels.color = textColor;
            }
            this.countChart.update();
        }

        if (this.inputChart && this.inputChart.options.plugins) {
            if (this.inputChart.options.plugins.legend) {
                this.inputChart.options.plugins.legend.labels.color = textColor;
            }
            this.inputChart.update();
        }

        if (this.outputChart && this.outputChart.options.plugins) {
            if (this.outputChart.options.plugins.legend) {
                this.outputChart.options.plugins.legend.labels.color = textColor;
            }
            this.outputChart.update();
        }

        if (this.tokensChart && this.tokensChart.options.scales) {
            this.tokensChart.options.scales.x.ticks.color = textColor;
            this.tokensChart.options.scales.y.ticks.color = textColor;
            this.tokensChart.options.scales.y1.ticks.color = textColor;
            this.tokensChart.options.scales.x.grid.color = gridColor;
            this.tokensChart.options.scales.y.grid.color = gridColor;
            this.tokensChart.options.scales.y1.grid.color = gridColor;
            this.tokensChart.options.scales.y.title.color = textColor;
            this.tokensChart.options.scales.y1.title.color = textColor;
            if (this.tokensChart.options.plugins && this.tokensChart.options.plugins.legend) {
                this.tokensChart.options.plugins.legend.labels.color = textColor;
            }
            this.tokensChart.update();
        }
    }

    // ===== Language Management Methods =====

    confirmRemoveLanguage(language) {
        this.languageToRemove = language;
        this.$removeLanguageName.text(language);
        this.$removeLanguageModal.fadeIn(200);
    }

    closeRemoveLanguageModal() {
        this.$removeLanguageModal.fadeOut(200);
        this.languageToRemove = null;
    }

    confirmRemoveLanguageOk() {
        if (this.languageToRemove) {
            this.removeLanguage(this.languageToRemove);
            this.closeRemoveLanguageModal();
        }
    }

    removeLanguage(language) {
        const self = this;

        $.ajax({
            url: '/remove_language',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ language: language }),
            success: function (response) {
                if (response.status === 'success') {
                    self.loadConfigOverview();
                } else {
                    alert('Error removing language ' + language + ": " + response.message);
                }
            },
            error: function (xhr, status, error) {
                console.error('Error removing language:', error);
                alert('Error removing language: ' + (xhr.responseJSON ? xhr.responseJSON.message : error));
            }
        });
    }

    openLanguageModal() {
        // Use the currently selected project from the config
        const selectedProject = this.getSelectedProject();
        const projectName = selectedProject ? selectedProject.name : (this.activeProjectName || 'Unknown');
        this.$modalProjectName.text(projectName);
        this.loadAvailableLanguages();
        this.$addLanguageModal.fadeIn(200);
    }

    getSelectedProject() {
        // Get the currently selected project from the config data
        if (!this.configData) return null;
        
        const activeProjects = this.configData.active_projects || [];
        if (activeProjects.length === 0) {
            // Fallback to backward compat
            return this.configData.active_project;
        }
        
        // Find the project matching the active project name
        const foundProject = activeProjects.find(p => p.name === this.activeProjectName);
        return foundProject || activeProjects[0];
    }

    closeLanguageModal() {
        this.$addLanguageModal.fadeOut(200);
        this.$modalLanguageSelect.empty();
        this.$modalAddBtn.prop('disabled', false).text('Add Language');
    }

    loadAvailableLanguages() {
        let self = this;
        $.ajax({
            url: '/get_available_languages',
            type: 'GET',
            success: function (response) {
                const languages = response.languages || [];
                self.$modalLanguageSelect.empty();

                if (languages.length === 0) {
                    self.$modalLanguageSelect.append($('<option>').val('').text('No languages available to add'));
                    self.$modalAddBtn.prop('disabled', true);
                } else {
                    languages.forEach(function (language) {
                        self.$modalLanguageSelect.append($('<option>').val(language).text(language));
                    });
                    self.$modalAddBtn.prop('disabled', false);
                }
            },
            error: function (xhr, status, error) {
                console.error('Error loading available languages:', error);
            }
        });
    }

    addLanguageFromModal() {
        const selectedLanguage = this.$modalLanguageSelect.val();
        if (!selectedLanguage) {
            alert('No language selected or no languages available to add');
            return;
        }

        const self = this;

        self.closeLanguageModal();

        $('#add-language-btn').hide();
        $('#add-language-spinner').show();
        self.isAddingLanguage = true;

        $.ajax({
            url: '/add_language',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ language: selectedLanguage }),
            success: function (response) {
                if (response.status === 'success') {
                    console.log("Language added successfully");
                } else {
                    alert('Error adding language ' + selectedLanguage + ": " + response.message);
                    $('#add-language-btn').show();
                    $('#add-language-spinner').hide();
                }
            },
            error: function (xhr, status, error) {
                console.error('Error adding language:', error);
                alert('Error adding language: ' + (xhr.responseJSON ? xhr.responseJSON.message : error));
                $('#add-language-btn').show();
                $('#add-language-spinner').hide();
            },
            complete: function () {
                self.isAddingLanguage = false;
                self.loadConfigOverview();
            }
        });
    }

    // ===== Memory Editing Methods =====

    openEditMemoryModal(memoryName) {
        const self = this;
        this.currentMemoryName = memoryName;
        this.memoryContentDirty = false;

        this.$editMemoryName.text(memoryName);

        $.ajax({
            url: '/get_memory',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ memory_name: memoryName }),
            success: function (response) {
                if (response.status === 'error') {
                    alert('Error: ' + response.message);
                    return;
                }
                self.originalMemoryContent = response.content;
                self.$editMemoryContent.val(response.content);
                self.memoryContentDirty = false;
                self.$editMemoryModal.fadeIn(200);
            },
            error: function (xhr, status, error) {
                console.error('Error loading memory:', error);
                alert('Error loading memory: ' + (xhr.responseJSON ? xhr.responseJSON.message : error));
            }
        });
    }

    closeEditMemoryModal() {
        if (this.memoryContentDirty) {
            if (!confirm('You have unsaved changes. Are you sure you want to close?')) {
                return;
            }
        }

        this.$editMemoryModal.fadeOut(200);
        this.currentMemoryName = null;
        this.originalMemoryContent = null;
        this.memoryContentDirty = false;
    }

    trackMemoryChanges() {
        const currentContent = this.$editMemoryContent.val();
        this.memoryContentDirty = (currentContent !== this.originalMemoryContent);
    }

    saveMemoryFromModal() {
        const self = this;
        const memoryName = this.currentMemoryName;
        const content = this.$editMemoryContent.val();

        if (!memoryName) {
            alert('No memory selected');
            return;
        }

        self.$editMemorySaveBtn.prop('disabled', true).text('Saving...');

        $.ajax({
            url: '/save_memory',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ memory_name: memoryName, content: content }),
            success: function (response) {
                if (response.status === 'success') {
                    self.originalMemoryContent = content;
                    self.memoryContentDirty = false;
                    self.$editMemoryModal.fadeOut(200);
                    self.currentMemoryName = null;
                } else {
                    alert('Error: ' + response.message);
                }
            },
            error: function (xhr, status, error) {
                console.error('Error saving memory:', error);
                alert('Error saving memory: ' + (xhr.responseJSON ? xhr.responseJSON.message : error));
            },
            complete: function () {
                self.$editMemorySaveBtn.prop('disabled', false).text('Save Changes');
            }
        });
    }

    startMemoryRename() {
        this.$editMemoryName.hide();
        this.$editMemoryRenameBtn.hide();
        this.$editMemoryRenameInput.val(this.currentMemoryName).show().focus().select();
    }

    cancelMemoryRename() {
        this.$editMemoryRenameInput.hide();
        this.$editMemoryName.show();
        this.$editMemoryRenameBtn.show();
    }

    commitMemoryRename() {
        const newName = this.$editMemoryRenameInput.val().trim();
        const oldName = this.currentMemoryName;

        if (!newName || newName === oldName) {
            this.cancelMemoryRename();
            return;
        }

        if (!/^[a-zA-Z0-9_]+(?:\/[a-zA-Z0-9_]+)*$/.test(newName)) {
            alert('Memory name can only contain letters, numbers, underscores, and "/" for subdirectories');
            this.$editMemoryRenameInput.focus();
            return;
        }

        const self = this;
        this.$editMemoryRenameInput.prop('disabled', true);

        $.ajax({
            url: '/rename_memory',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ old_name: oldName, new_name: newName }),
            success: function (response) {
                if (response.status === 'success') {
                    self.currentMemoryName = newName;
                    self.$editMemoryName.text(newName);
                    self.cancelMemoryRename();
                    self.loadConfigOverview();
                } else {
                    alert('Error: ' + response.message);
                    self.$editMemoryRenameInput.focus();
                }
            },
            error: function (xhr, status, error) {
                console.error('Error renaming memory:', error);
                alert('Error renaming memory: ' + (xhr.responseJSON ? xhr.responseJSON.message : error));
                self.$editMemoryRenameInput.focus();
            },
            complete: function () {
                self.$editMemoryRenameInput.prop('disabled', false);
            }
        });
    }

    confirmDeleteMemory(memoryName) {
        this.memoryToDelete = memoryName;
        this.$deleteMemoryName.text(memoryName);
        this.$deleteMemoryModal.fadeIn(200);
    }

    closeDeleteMemoryModal() {
        this.$deleteMemoryModal.fadeOut(200);
        this.memoryToDelete = null;
    }

    confirmDeleteMemoryOk() {
        if (this.memoryToDelete) {
            this.deleteMemory(this.memoryToDelete);
            this.closeDeleteMemoryModal();
        }
    }

    deleteMemory(memoryName) {
        const self = this;

        $.ajax({
            url: '/delete_memory',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ memory_name: memoryName }),
            success: function (response) {
                if (response.status === 'success') {
                    self.loadConfigOverview();
                } else {
                    alert('Error: ' + response.message);
                }
            },
            error: function (xhr, status, error) {
                console.error('Error deleting memory:', error);
                alert('Error deleting memory: ' + (xhr.responseJSON ? xhr.responseJSON.message : error));
            }
        });
    }

    openCreateMemoryModal() {
        // Use the currently selected project from the config
        const selectedProject = this.getSelectedProject();
        const projectName = selectedProject ? selectedProject.name : (this.activeProjectName || 'Unknown');
        this.$createMemoryProjectName.text(projectName);
        this.$createMemoryNameInput.val('');
        this.$createMemoryModal.fadeIn(200);
        setTimeout(() => {
            this.$createMemoryNameInput.focus();
        }, 250);
    }

    closeCreateMemoryModal() {
        this.$createMemoryModal.fadeOut(200);
        this.$createMemoryNameInput.val('');
        this.$createMemoryCreateBtn.prop('disabled', false).text('Create');
    }

    createMemoryFromModal() {
        const memoryName = this.$createMemoryNameInput.val().trim();

        if (!memoryName) {
            alert('Please enter a memory name');
            return;
        }

        if (!/^[a-zA-Z0-9_]+(?:\/[a-zA-Z0-9_]+)*$/.test(memoryName)) {
            alert('Memory name can only contain letters, numbers, underscores, and "/" for subdirectories');
            return;
        }

        const self = this;

        self.$createMemoryCreateBtn.prop('disabled', true).text('Creating...');

        $.ajax({
            url: '/save_memory',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ memory_name: memoryName, content: '' }),
            success: function (response) {
                if (response.status === 'success') {
                    self.closeCreateMemoryModal();
                    self.loadConfigOverview();
                    setTimeout(() => {
                        self.openEditMemoryModal(memoryName);
                    }, 500);
                } else {
                    alert('Error: ' + response.message);
                    self.$createMemoryCreateBtn.prop('disabled', false).text('Create');
                }
            },
            error: function (xhr, status, error) {
                console.error('Error creating memory:', error);
                alert('Error creating memory: ' + (xhr.responseJSON ? xhr.responseJSON.message : error));
                self.$createMemoryCreateBtn.prop('disabled', false).text('Create');
            }
        });
    }

    // ===== News Methods =====

    loadNews() {
        let self = this;
        console.log('Loading news...');
        $.ajax({
            url: '/fetch_unread_news',
            type: 'GET',
            success: function(response) {
                console.log('Unread news response:', response);
                if (response.status === 'success' && response.news && Object.keys(response.news).length > 0) {
                    const newsIds = Object.keys(response.news);
                    self.displayNews(newsIds, response.news);
                } else {
                    console.log('No unread news, hiding section');
                    self.$newsSection.hide();
                }
            },
            error: function(xhr, status, error) {
                console.error('Error loading news:', error);
                self.$newsSection.hide();
            }
        });
    }

    displayNews(newsIds, newsData) {
        let self = this;
        console.log('displayNews called with:', newsIds);
        newsIds.sort((a, b) => b - a);

        if (newsIds.length === 0) {
            self.$newsSection.hide();
            return;
        }
        self.$newsSection.show();
        self.$newsDisplay.empty();

        newsIds.forEach(function(newsId) {
            const html = newsData[String(newsId)];
            if (!html) return;

            let $newsContainer = $('<div class="news-container">').attr('data-news-id', newsId);
            let $newsContent = $(html);

            let $markRead = $('<div class="news-mark-read">');
            let $button = $('<button class="news-mark-read-btn">').attr('data-news-id', newsId).text('Mark as read');

            $markRead.append($button);
            $newsContent.append($markRead);

            $newsContainer.append($newsContent);
            self.$newsDisplay.append($newsContainer);

            $button.on('click', function() {
                const btn = $(this);
                btn.prop('disabled', true).text('Marking...');
                self.markNewsAsRead(newsId);
            });
        });
    }

    markNewsAsRead(newsId) {
        let self = this;
        $.ajax({
            url: '/mark_news_snippet_as_read',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ news_snippet_id: newsId }),
            success: function(response) {
                if (response.status === 'success') {
                    self.loadNews();
                } else {
                    console.error('Error marking news as read:', response.message);
                }
            },
            error: function(xhr, status, error) {
                console.error('Error marking news as read:', error);
            }
        });
    }

    // ===== Serena Config Editing Methods =====

    openEditSerenaConfigModal() {
        const self = this;
        this.serenaConfigContentDirty = false;

        $.ajax({
            url: '/get_serena_config',
            type: 'GET',
            success: function (response) {
                if (response.status === 'error') {
                    alert('Error: ' + response.message);
                    return;
                }
                self.originalSerenaConfigContent = response.content;
                self.$editSerenaConfigContent.val(response.content);
                self.serenaConfigContentDirty = false;
                self.$editSerenaConfigModal.fadeIn(200);
            },
            error: function (xhr, status, error) {
                console.error('Error loading serena config:', error);
                alert('Error loading serena config: ' + (xhr.responseJSON ? xhr.responseJSON.message : error));
            }
        });

        this.$editSerenaConfigContent.off('input').on('input', function () {
            const currentContent = self.$editSerenaConfigContent.val();
            self.serenaConfigContentDirty = (currentContent !== self.originalSerenaConfigContent);
        });
    }

    closeEditSerenaConfigModal() {
        if (this.serenaConfigContentDirty) {
            if (!confirm('You have unsaved changes. Are you sure you want to close?')) {
                return;
            }
        }

        this.$editSerenaConfigModal.fadeOut(200);
        this.originalSerenaConfigContent = null;
        this.serenaConfigContentDirty = false;
    }

    saveSerenaConfigFromModal() {
        const self = this;
        const content = this.$editSerenaConfigContent.val();

        self.$editSerenaConfigSaveBtn.prop('disabled', true).text('Saving...');

        $.ajax({
            url: '/save_serena_config',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ content: content }),
            success: function (response) {
                if (response.status === 'success') {
                    self.originalSerenaConfigContent = content;
                    self.serenaConfigContentDirty = false;
                    self.$editSerenaConfigModal.fadeOut(200);
                    alert('Configuration saved successfully. Please restart Serena for changes to take effect.');
                } else {
                    alert('Error: ' + response.message);
                }
            },
            error: function (xhr, status, error) {
                console.error('Error saving serena config:', error);
                alert('Error saving serena config: ' + (xhr.responseJSON ? xhr.responseJSON.message : error));
            },
            complete: function () {
                self.$editSerenaConfigSaveBtn.prop('disabled', false).text('Save Configuration');
            }
        });
    }

    // ===== Shutdown Method =====

    shutdown() {
        const self = this;
        const _shutdown = function () {
            console.log("Triggering shutdown");
            $.ajax({
                url: '/shutdown',
                type: "PUT",
                contentType: 'application/json',
            });
            self.$errorContainer.html('<div class="error-message">Shutting down ...</div>');
            setTimeout(function () {
                window.close();
            }, 1000);
        };

        if (confirm("This will fully terminate the Serena server.")) {
            _shutdown();
        } else {
            console.log("Shutdown cancelled");
        }

        self.$menuDropdown.hide();
    }
}
