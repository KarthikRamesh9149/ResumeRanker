// NO IMPORTS - This is a dynamic window!
// All dependencies are provided globally by the app

const ResumeRankerWindow = () => {
  // Server state
  const [serverOnline, setServerOnline] = React.useState(false);
  const [availableVenvs, setAvailableVenvs] = React.useState<string[]>([]);
  const [selectedVenv, setSelectedVenv] = React.useState('');
  const [serverPort, setServerPort] = React.useState(8892);
  const [serverRunning, setServerRunning] = React.useState(false);
  const [connecting, setConnecting] = React.useState(false);
  const [checkingDeps, setCheckingDeps] = React.useState(false);
  const [installingDeps, setInstallingDeps] = React.useState(false);
  const [installingPackage, setInstallingPackage] = React.useState('');
  const [depsStatus, setDepsStatus] = React.useState<Record<string, { installed: boolean; version?: string }>>({});
  const [serverStatus, setServerStatus] = React.useState<any>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [creatingVenv, setCreatingVenv] = React.useState(false);

  // Workflow state
  const [activeTab, setActiveTab] = React.useState('setup');
  const [folderPath, setFolderPath] = React.useState('');
  const [files, setFiles] = React.useState<any[]>([]);
  const [fileCount, setFileCount] = React.useState(0);
  const [scanning, setScanning] = React.useState(false);
  const [folderError, setFolderError] = React.useState<string | null>(null);
  const [useLlm, setUseLlm] = React.useState(false);
  const [useLlmForJd, setUseLlmForJd] = React.useState(true);
  const [llmEnabled, setLlmEnabled] = React.useState(false);
  const [ranking, setRanking] = React.useState(false);
  const [rankError, setRankError] = React.useState<string | null>(null);
  const [scanComplete, setScanComplete] = React.useState(false);
  const [topN, setTopN] = React.useState(5);
  const [useDeepEval, setUseDeepEval] = React.useState(true);

  // Multiple JD entries
  const [jdEntries, setJdEntries] = React.useState<any[]>([]);
  // Each entry: { id, filePath, fileName, text, requirements, analyzing, results }
  const [activeJdId, setActiveJdId] = React.useState<string | null>(null);
  const [newSkillInputs, setNewSkillInputs] = React.useState<Record<string, { required: string; preferred: string }>>({});

  const generateId = () => Math.random().toString(36).substr(2, 9);

  const REQUIRED_PACKAGES = [
    'fastapi', 'uvicorn', 'pydantic', 'python-dotenv', 'requests',
    'scikit-learn', 'numpy', 'scipy', 'joblib', 'python-docx', 'pymupdf'
  ];

  const getServerUrl = () => `http://127.0.0.1:${serverPort}`;

  const normalizePackageName = (name: string): string => name.toLowerCase().replace(/-/g, '_');

  const parsePackageInfo = (pkgStr: string): { name: string; version?: string } => {
    if (pkgStr.includes(' @ ')) {
      const name = pkgStr.split(' @ ')[0].trim();
      return { name, version: 'local' };
    }
    if (pkgStr.includes('==')) {
      const [name, version] = pkgStr.split('==');
      return { name: name.trim(), version: version?.trim() };
    }
    const parts = pkgStr.split(' ');
    return { name: parts[0].trim(), version: parts[1]?.trim() };
  };

  const checkDeps = async () => {
    const ipcRenderer = (window as any).require?.('electron')?.ipcRenderer;
    if (!ipcRenderer || !selectedVenv) return;

    setCheckingDeps(true);
    try {
      const vres = await ipcRenderer.invoke('python-list-venvs', { refresh: true });
      if (vres.success) {
        const v = (vres.venvs || []).find((x: any) => x.name === selectedVenv);
        if (v && Array.isArray(v.packages)) {
          const map: Record<string, { installed: boolean; version?: string }> = {};
          for (const pkg of REQUIRED_PACKAGES) {
            const normalizedPkg = normalizePackageName(pkg);
            const found = v.packages.find((p: string) => {
              const parsed = parsePackageInfo(p);
              return normalizePackageName(parsed.name) === normalizedPkg;
            });
            if (found) {
              const parsed = parsePackageInfo(found);
              map[pkg] = { installed: true, version: parsed.version };
            } else {
              map[pkg] = { installed: false };
            }
          }
          setDepsStatus(map);
        }
      }
    } catch (e: any) {
      console.error('Error checking deps:', e);
    } finally {
      setCheckingDeps(false);
    }
  };

  // Poll server status
  React.useEffect(() => {
    const checkStatus = async () => {
      try {
        const res = await fetch(`${getServerUrl()}/status`);
        const data = await res.json();
        setServerOnline(data.ready);
        setServerStatus(data);
        setServerRunning(true);
        setLlmEnabled(data.llm_enabled || false);
      } catch {
        setServerOnline(false);
        setServerRunning(false);
        setServerStatus(null);
      }
    };

    checkStatus();
    const interval = setInterval(checkStatus, 2000);
    return () => clearInterval(interval);
  }, [serverPort]);

  // Load available venvs
  const loadVenvs = async () => {
    const ipcRenderer = (window as any).require?.('electron')?.ipcRenderer;
    if (!ipcRenderer) return;

    const result = await ipcRenderer.invoke('python-list-venvs');
    if (result.success && result.venvs.length > 0) {
      const names = result.venvs.map((v: any) => v.name);
      setAvailableVenvs(names);
      if (!selectedVenv) {
        // Prefer 'resumeranker' venv if it exists
        if (names.includes('resumeranker')) {
          setSelectedVenv('resumeranker');
        } else {
          setSelectedVenv(names[0]);
        }
      }
    }
  };

  React.useEffect(() => {
    loadVenvs();
  }, []);

  // Create a new venv
  const createVenv = async (venvName: string) => {
    const ipcRenderer = (window as any).require?.('electron')?.ipcRenderer;
    if (!ipcRenderer) return;

    setCreatingVenv(true);
    setError(null);

    try {
      const result = await ipcRenderer.invoke('python-create-venv', {
        venvName: venvName,
        pythonVersion: '3.12'
      });

      if (result.success) {
        // Refresh venv list and select the new one
        await loadVenvs();
        setSelectedVenv(venvName);
      } else {
        setError(`Failed to create venv: ${result.error}`);
      }
    } catch (e: any) {
      setError(`Error creating venv: ${e.message}`);
    } finally {
      setCreatingVenv(false);
    }
  };

  // Auto-check deps when venv changes
  React.useEffect(() => {
    if (selectedVenv) {
      checkDeps();
    }
  }, [selectedVenv]);

  const startServer = async () => {
    const ipcRenderer = (window as any).require?.('electron')?.ipcRenderer;
    if (!ipcRenderer) {
      setError('Not running in Electron environment');
      return;
    }

    setConnecting(true);
    setError(null);

    if (!selectedVenv) {
      setError('Please select a Python virtual environment');
      setConnecting(false);
      return;
    }

    // Get the script path
    const scriptResult = await ipcRenderer.invoke('resolve-workflow-script', {
      workflowFolder: 'user_workflows/ResumeRanker',
      scriptName: 'resumeranker_server.py'
    });

    if (!scriptResult.success) {
      setError(`Could not find server script: ${scriptResult.error}`);
      setConnecting(false);
      return;
    }

    const result = await ipcRenderer.invoke('python-start-script-server', {
      venvName: selectedVenv,
      scriptPath: scriptResult.path,
      port: serverPort,
      serverName: 'resumeranker',
    });

    if (result.success) {
      // Poll for server connection
      let attempts = 0;
      const maxAttempts = 30;
      const pollInterval = setInterval(async () => {
        attempts++;
        try {
          const res = await fetch(`${getServerUrl()}/status`);
          if (res.ok) {
            const data = await res.json();
            setServerStatus(data);
            setServerRunning(true);
            setServerOnline(true);
            setConnecting(false);
            setLlmEnabled(data.llm_enabled || false);
            clearInterval(pollInterval);
          }
        } catch (e) {
          if (attempts >= maxAttempts) {
            clearInterval(pollInterval);
            setError('Server failed to start within timeout. Check console for details.');
            setConnecting(false);
          }
        }
      }, 1000);
    } else {
      setError(`Failed to start server: ${result.error}`);
      setConnecting(false);
    }
  };

  const stopServer = async () => {
    const ipcRenderer = (window as any).require?.('electron')?.ipcRenderer;
    if (!ipcRenderer) return;

    const result = await ipcRenderer.invoke('python-stop-script-server', 'resumeranker');
    if (result.success) {
      setServerRunning(false);
      setServerOnline(false);
      setServerStatus(null);
    } else {
      try {
        await fetch(`${getServerUrl()}/shutdown`, { method: 'POST' });
      } catch {}
      setServerRunning(false);
      setServerOnline(false);
      setServerStatus(null);
    }
  };

  const installMissingDeps = async () => {
    const ipcRenderer = (window as any).require?.('electron')?.ipcRenderer;
    if (!ipcRenderer) return;

    setInstallingDeps(true);

    for (const pkg of REQUIRED_PACKAGES) {
      if (!depsStatus[pkg]?.installed) {
        setInstallingPackage(pkg);
        const result = await ipcRenderer.invoke('python-install-package', {
          venvName: selectedVenv,
          package: pkg,
        });
        console.log(`Install ${pkg}:`, result);
      }
    }

    setInstallingPackage('');
    setInstallingDeps(false);
    await checkDeps();
  };

  // Browse for folder
  const handleBrowseFolder = async () => {
    const ipcRenderer = (window as any).require?.('electron')?.ipcRenderer;
    if (!ipcRenderer) return;

    try {
      const result = await ipcRenderer.invoke('show-open-dialog', {
        properties: ['openDirectory'],
        title: 'Select Resume Folder'
      });

      if (result && !result.canceled && result.filePaths && result.filePaths.length > 0) {
        setFolderPath(result.filePaths[0]);
        setFolderError(null);
      }
    } catch (e: any) {
      console.error('Error opening folder dialog:', e);
    }
  };

  // Scan folder
  const handleScanFolder = async () => {
    if (!folderPath.trim()) {
      setFolderError('Please enter a folder path');
      return;
    }

    setScanning(true);
    setFolderError(null);
    setFiles([]);
    setFileCount(0);
    setScanComplete(false);

    try {
      const res = await fetch(`${getServerUrl()}/scan_folder`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ folder_path: folderPath.trim() }),
      });

      const data = await res.json();

      if (data.success) {
        setFiles(data.files || []);
        setFileCount(data.count || 0);
        setFolderError(null);
        setScanComplete(true);
      } else {
        setFolderError(data.error || 'Failed to scan folder');
        setScanComplete(false);
      }
    } catch (err) {
      setFolderError('Failed to connect to server');
      setScanComplete(false);
    } finally {
      setScanning(false);
    }
  };

  // Analyze a single JD entry (called automatically after file upload or manually)
  const analyzeJdEntry = async (entryId: string, filePath?: string, text?: string) => {
    setJdEntries(prev => prev.map(e => e.id === entryId ? { ...e, analyzing: true, results: [] } : e));
    setRankError(null);

    try {
      const res = await fetch(`${getServerUrl()}/analyze_jd`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          job_description: text || '',
          jd_file_path: filePath || '',
          use_llm: useLlmForJd,
        }),
      });

      const data = await res.json();

      if (data.success) {
        if (data.roles && data.roles.length > 1) {
          // Multiple roles detected in one document - split into separate entries
          setJdEntries(prev => {
            const originalEntry = prev.find(e => e.id === entryId);
            const baseFileName = originalEntry?.fileName || filePath?.split(/[/\\]/).pop() || 'JD';
            const baseFilePath = filePath || originalEntry?.filePath || '';
            const baseText = text || originalEntry?.text || '';

            const filtered = prev.filter(e => e.id !== entryId);
            const newEntries = data.roles.map((role: any) => ({
              id: generateId(),
              filePath: baseFilePath,
              fileName: `${baseFileName} [${role.role_label}]`,
              text: role.section_text || baseText,  // Role-specific text for domain matching; falls back to full JD
              requirements: role.requirements,
              analyzing: false,
              results: [],
            }));
            return [...filtered, ...newEntries];
          });
        } else if (data.requirements) {
          setJdEntries(prev => prev.map(e => e.id === entryId ? { ...e, requirements: data.requirements, analyzing: false } : e));
        } else {
          setRankError('Failed to extract skills from job description');
          setJdEntries(prev => prev.map(e => e.id === entryId ? { ...e, analyzing: false } : e));
        }
      } else {
        setRankError(data.error || 'Failed to analyze job description');
        setJdEntries(prev => prev.map(e => e.id === entryId ? { ...e, analyzing: false } : e));
      }
    } catch (err) {
      setRankError('Failed to connect to server for JD analysis');
      setJdEntries(prev => prev.map(e => e.id === entryId ? { ...e, analyzing: false } : e));
    }
  };

  // Browse and add a JD file
  const handleAddJdFile = async () => {
    const ipcRenderer = (window as any).require?.('electron')?.ipcRenderer;
    if (!ipcRenderer) return;

    try {
      const result = await ipcRenderer.invoke('show-open-dialog', {
        properties: ['openFile', 'multiSelections'],
        title: 'Select Job Description File(s)',
        filters: [
          { name: 'Documents', extensions: ['pdf', 'docx', 'txt'] }
        ]
      });

      if (result && !result.canceled && result.filePaths && result.filePaths.length > 0) {
        for (const filePath of result.filePaths) {
          const fileName = filePath.split(/[/\\]/).pop() || 'file';
          const id = generateId();
          const newEntry = { id, filePath, fileName, text: '', requirements: null, analyzing: false, results: [] };
          setJdEntries(prev => [...prev, newEntry]);
          // Auto-analyze each JD
          analyzeJdEntry(id, filePath);
        }
      }
    } catch (e: any) {
      console.error('Error opening file dialog:', e);
    }
  };

  // Remove a JD entry
  const handleRemoveJd = (entryId: string) => {
    setJdEntries(prev => prev.filter(e => e.id !== entryId));
    if (activeJdId === entryId) setActiveJdId(null);
  };

  // Skill editing helpers (per JD entry)
  const removeSkill = (entryId: string, type: 'required' | 'preferred', index: number) => {
    setJdEntries(prev => prev.map(e => {
      if (e.id !== entryId || !e.requirements) return e;
      const updated = { ...e.requirements };
      if (type === 'required') {
        updated.required_skills = updated.required_skills.filter((_: any, i: number) => i !== index);
      } else {
        updated.preferred_skills = updated.preferred_skills.filter((_: any, i: number) => i !== index);
      }
      return { ...e, requirements: updated };
    }));
  };

  const addSkill = (entryId: string, type: 'required' | 'preferred') => {
    const inputs = newSkillInputs[entryId] || { required: '', preferred: '' };
    const skill = type === 'required' ? inputs.required : inputs.preferred;
    if (!skill.trim()) return;

    setJdEntries(prev => prev.map(e => {
      if (e.id !== entryId || !e.requirements) return e;
      const updated = { ...e.requirements };
      if (type === 'required') {
        if (!updated.required_skills.includes(skill.trim())) {
          updated.required_skills = [...updated.required_skills, skill.trim()];
        }
      } else {
        if (!updated.preferred_skills.includes(skill.trim())) {
          updated.preferred_skills = [...updated.preferred_skills, skill.trim()];
        }
      }
      return { ...e, requirements: updated };
    }));

    setNewSkillInputs(prev => ({
      ...prev,
      [entryId]: { ...inputs, [type]: '' }
    }));
  };

  const updateSkillInput = (entryId: string, type: 'required' | 'preferred', value: string) => {
    setNewSkillInputs(prev => ({
      ...prev,
      [entryId]: { ...(prev[entryId] || { required: '', preferred: '' }), [type]: value }
    }));
  };

  // Rank resumes against ALL JDs
  const handleRankResumes = async () => {
    const readyEntries = jdEntries.filter(e => e.requirements || e.filePath || e.text?.trim());
    if (!folderPath.trim() || readyEntries.length === 0) {
      setRankError('Folder and at least one job description are required');
      return;
    }

    setRanking(true);
    setRankError(null);
    // Clear previous results
    setJdEntries(prev => prev.map(e => ({ ...e, results: [] })));

    try {
      const res = await fetch(`${getServerUrl()}/rank_multi`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          folder_path: folderPath.trim(),
          jd_entries: readyEntries.map(e => ({
            jd_text: e.text || '',
            jd_file_path: e.filePath || '',
            requirements: e.requirements || undefined,
            jd_label: e.fileName || 'Pasted JD',
          })),
          use_llm: useLlm,
          use_llm_for_jd: useLlmForJd,
          use_deep_eval: useDeepEval,
          top_n: topN,
        }),
      });

      const data = await res.json();

      if (data.success && data.results) {
        // Map results back to JD entries by order
        setJdEntries(prev => {
          const readyIds = prev.filter(e => e.requirements || e.filePath || e.text?.trim()).map(e => e.id);
          return prev.map(e => {
            const idx = readyIds.indexOf(e.id);
            if (idx >= 0 && data.results[idx]) {
              return {
                ...e,
                results: data.results[idx].candidates || [],
                requirements: data.results[idx].requirements_used || e.requirements,
              };
            }
            return e;
          });
        });
        // Auto-select first JD with results
        if (!activeJdId && readyEntries.length > 0) {
          setActiveJdId(readyEntries[0].id);
        }
        setRankError(null);
      } else {
        setRankError(data.error || 'Failed to rank resumes');
      }
    } catch (err) {
      setRankError('Failed to connect to server');
    } finally {
      setRanking(false);
    }
  };

  // Open file
  const handleOpenFile = async (filePath: string) => {
    try {
      const res = await fetch(`${getServerUrl()}/open_file`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          path: filePath,
          root_folder: folderPath.trim(),
        }),
      });

      const data = await res.json();

      if (!data.success) {
        alert(data.error || 'Failed to open file');
      }
    } catch (err) {
      alert('Failed to connect to server');
    }
  };

  const getScoreColor = (score: number) => {
    if (score >= 70) return 'text-emerald-400';
    if (score >= 50) return 'text-amber-400';
    return 'text-red-400';
  };

  const getScoreBg = (score: number) => {
    if (score >= 70) return 'bg-emerald-500/10 border-emerald-500/30';
    if (score >= 50) return 'bg-amber-500/10 border-amber-500/30';
    return 'bg-red-500/10 border-red-500/30';
  };

  const hasJdReady = jdEntries.some(e => e.requirements || e.filePath || e.text?.trim());
  const anyAnalyzing = jdEntries.some(e => e.analyzing);
  const canRank = fileCount > 0 && hasJdReady && !ranking && !anyAnalyzing;
  const activeJdEntry = jdEntries.find(e => e.id === activeJdId);
  const activeResults = activeJdEntry?.results || [];
  const allDepsInstalled = REQUIRED_PACKAGES.every(p => depsStatus[p]?.installed);

  return (
    <div className="flex flex-col h-full bg-gray-900 text-gray-100">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 bg-gray-800 border-b border-gray-700">
        <div className="flex items-center gap-3">
          <div className="text-xl font-bold text-blue-400">ResumeRanker</div>
          <div className="text-xs text-gray-400">Local Resume Ranking</div>
        </div>
        <div className="flex items-center gap-2">
          <div className={`w-2 h-2 rounded-full ${serverOnline ? 'bg-emerald-400' : 'bg-red-400'}`} />
          <span className="text-xs text-gray-400">
            {serverOnline ? 'Server online' : 'Server offline'}
          </span>
        </div>
      </div>

      {error && (
        <div className="px-4 py-2 bg-red-900/30 border-b border-red-700/50 text-red-300 text-sm">
          {error}
        </div>
      )}

      {/* Tabs */}
      <div className="flex border-b border-gray-700 bg-gray-800">
        {['setup', 'rank'].map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 text-sm font-medium transition-colors ${
              activeTab === tab
                ? 'text-blue-400 border-b-2 border-blue-400'
                : 'text-gray-400 hover:text-gray-200'
            }`}
          >
            {tab.charAt(0).toUpperCase() + tab.slice(1)}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      <div className="flex-1 overflow-auto p-4">
        {/* Setup Tab */}
        {activeTab === 'setup' && (
          <div className="space-y-4 max-w-2xl mx-auto">
            {/* Server Connection Section */}
            <div className="bg-gray-800 rounded p-4 border border-gray-700">
              <h4 className="m-0 mb-3 text-[13px] font-medium text-gray-300">Server Connection</h4>
              <div className="flex items-center gap-2.5 mb-2 flex-wrap">
                <span className="text-[13px] text-gray-400">Venv:</span>
                <select
                  value={selectedVenv}
                  onChange={e => setSelectedVenv(e.target.value)}
                  className="bg-gray-700 border border-gray-600 rounded px-2 py-1 text-[13px] text-gray-100 focus:outline-none focus:border-blue-500 w-[140px]"
                  disabled={serverRunning}
                >
                  {availableVenvs.length === 0 ? (
                    <option value="">No venvs</option>
                  ) : (
                    availableVenvs.map(name => (
                      <option key={name} value={name}>{name}</option>
                    ))
                  )}
                </select>
                <span className="text-[13px] text-gray-400">Port:</span>
                <input
                  type="number"
                  value={serverPort}
                  onChange={e => setServerPort(parseInt(e.target.value) || 8892)}
                  className="bg-gray-700 border border-gray-600 rounded px-2 py-1 text-[13px] text-gray-100 focus:outline-none focus:border-blue-500 w-[70px]"
                  disabled={serverRunning}
                />
                {!serverRunning ? (
                  <button
                    onClick={startServer}
                    disabled={connecting || !selectedVenv || !allDepsInstalled}
                    className={`px-3 py-1 rounded text-[13px] font-medium transition-colors ${
                      connecting || !selectedVenv || !allDepsInstalled
                        ? 'bg-gray-600 opacity-50 cursor-not-allowed'
                        : 'bg-blue-600 hover:bg-blue-500 text-white'
                    }`}
                  >
                    {connecting ? 'Connecting...' : 'Start Server'}
                  </button>
                ) : (
                  <button
                    onClick={stopServer}
                    className="px-3 py-1 bg-red-600 hover:bg-red-500 rounded text-[13px] font-medium text-white transition-colors"
                  >
                    Stop Server
                  </button>
                )}
              </div>
              {serverStatus && (
                <div className="text-[11px] text-gray-400 mt-2">
                  {serverStatus.llm_enabled ? '✓ LLM Enabled (Groq)' : '✗ LLM Not Configured'}
                </div>
              )}
            </div>

            {/* Create Venv Section */}
            <div className="bg-gray-800 rounded p-4 border border-gray-700">
              <h4 className="m-0 mb-3 text-[13px] font-medium text-gray-300">Create Virtual Environment</h4>
              <div className="flex items-center gap-2">
                <span className="text-[11px] text-gray-400">
                  {availableVenvs.includes('resumeranker')
                    ? '✓ "resumeranker" venv exists'
                    : 'Create a dedicated venv for this workflow:'}
                </span>
                {!availableVenvs.includes('resumeranker') && (
                  <button
                    onClick={() => createVenv('resumeranker')}
                    disabled={creatingVenv || serverRunning}
                    className={`px-3 py-1 rounded text-[11px] font-medium transition-colors ${
                      creatingVenv || serverRunning
                        ? 'bg-gray-600 opacity-50 cursor-not-allowed'
                        : 'bg-emerald-600 hover:bg-emerald-500 text-white'
                    }`}
                  >
                    {creatingVenv ? 'Creating...' : 'Create "resumeranker" venv'}
                  </button>
                )}
              </div>
              {creatingVenv && (
                <div className="text-[11px] text-blue-400 mt-2 animate-pulse">
                  Creating virtual environment... This may take a minute.
                </div>
              )}
            </div>

            {/* Python Packages Section */}
            <div className="bg-gray-800 rounded p-4 border border-gray-700">
              <div className="flex items-center justify-between mb-3">
                <h4 className="m-0 text-[13px] font-medium text-gray-300">
                  Python Packages {checkingDeps && <span className="text-gray-500 font-normal text-[11px]">(checking...)</span>}
                </h4>
                <div className="flex gap-2">
                  <button
                    onClick={checkDeps}
                    disabled={!selectedVenv || checkingDeps}
                    className={`px-2 py-1 rounded text-[11px] font-medium transition-colors ${
                      !selectedVenv || checkingDeps
                        ? 'bg-gray-600 opacity-50 cursor-not-allowed'
                        : 'bg-gray-600 hover:bg-gray-500 text-white'
                    }`}
                  >
                    Refresh
                  </button>
                  <button
                    onClick={installMissingDeps}
                    disabled={!selectedVenv || installingDeps || allDepsInstalled}
                    className={`px-2 py-1 rounded text-[11px] font-medium transition-colors ${
                      allDepsInstalled
                        ? 'bg-gray-600 text-gray-400 cursor-not-allowed'
                        : 'bg-blue-600 hover:bg-blue-500 text-white'
                    }`}
                  >
                    {installingDeps ? `Installing ${installingPackage}...` : 'Install All'}
                  </button>
                </div>
              </div>
              <div className="grid grid-cols-3 gap-1.5">
                {REQUIRED_PACKAGES.map(pkg => {
                  const status = depsStatus[pkg];
                  const isInstalled = status?.installed;
                  return (
                    <div
                      key={pkg}
                      className={`py-1.5 px-2.5 rounded text-[11px] flex items-center gap-1.5 ${
                        isInstalled ? 'bg-emerald-500/15 text-emerald-300' : 'bg-red-500/15 text-red-300'
                      }`}
                    >
                      <span>{isInstalled ? '✓' : '✗'}</span>
                      <span>{pkg}</span>
                      {status?.version && <span className="text-gray-500 text-[10px]">({status.version})</span>}
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        )}

        {/* Rank Tab */}
        {activeTab === 'rank' && (
          <div>
            {!serverOnline ? (
              <div className="flex items-center justify-center h-64">
                <div className="text-center">
                  <div className="text-gray-400 mb-2">Server not connected</div>
                  <div className="text-sm text-gray-500">Go to the Setup tab to start the server</div>
                </div>
              </div>
            ) : (
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                {/* Panel A: Folder */}
                <div className="bg-gray-800 rounded-lg border border-gray-700 p-4 flex flex-col">
                  <h2 className="text-sm font-semibold text-gray-100 mb-3 flex items-center gap-2">
                    <span className="w-5 h-5 rounded bg-blue-600 flex items-center justify-center text-xs text-white">1</span>
                    Resume Folder
                  </h2>

                  <div className="space-y-3">
                    <div className="flex gap-2">
                      <input
                        type="text"
                        value={folderPath}
                        onChange={(e) => setFolderPath(e.target.value)}
                        placeholder="C:\Users\...\Resumes"
                        className="flex-1 bg-gray-900 border border-gray-600 text-gray-100 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 placeholder-gray-500"
                      />
                      <button
                        onClick={handleBrowseFolder}
                        className="px-3 py-2 bg-gray-700 hover:bg-gray-600 text-gray-200 rounded-lg text-sm font-medium transition-colors flex items-center gap-2"
                      >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
                        </svg>
                        Browse
                      </button>
                    </div>

                    <div className="flex gap-2">
                      <button
                        onClick={handleScanFolder}
                        disabled={scanning || !folderPath.trim()}
                        className="flex-1 px-3 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
                      >
                        {scanning && <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />}
                        {scanning ? 'Scanning...' : 'Scan Folder'}
                      </button>
                      <button
                        onClick={handleScanFolder}
                        disabled={scanning || fileCount === 0}
                        className="px-3 py-2 bg-gray-700 hover:bg-gray-600 text-gray-200 rounded-lg text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        Rescan
                      </button>
                    </div>

                    {folderError && (
                      <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-3">
                        <div className="text-red-400 text-sm">{folderError}</div>
                      </div>
                    )}

                    {scanComplete && fileCount > 0 && (
                      <div className="bg-emerald-500/10 border border-emerald-500/30 rounded-lg p-3">
                        <div className="flex items-center gap-2 text-emerald-400 text-sm font-medium mb-2">
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                          </svg>
                          Scan Complete
                        </div>
                        <div className="text-gray-200 text-sm mb-2">
                          Found {fileCount} resume{fileCount !== 1 ? 's' : ''} ready for ranking
                        </div>
                        <div className="space-y-1 max-h-32 overflow-auto">
                          {files.slice(0, 10).map((file: any, idx: number) => (
                            <div key={idx} className="text-xs text-gray-400 flex items-center gap-2">
                              <span className="w-4 h-4 rounded bg-gray-700 flex items-center justify-center text-[10px] uppercase text-gray-300">
                                {file.ext.replace('.', '')}
                              </span>
                              <span className="truncate">{file.name}</span>
                            </div>
                          ))}
                          {files.length > 10 && (
                            <div className="text-xs text-gray-500">...and {files.length - 10} more</div>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                </div>

                {/* Panel B: Job Descriptions (Multiple) */}
                <div className="bg-gray-800 rounded-lg border border-gray-700 p-4 flex flex-col">
                  <h2 className="text-sm font-semibold text-gray-100 mb-3 flex items-center gap-2">
                    <span className="w-5 h-5 rounded bg-blue-600 flex items-center justify-center text-xs text-white">2</span>
                    Job Descriptions ({jdEntries.length})
                  </h2>

                  <div className="flex-1 flex flex-col space-y-3 overflow-auto">
                    {/* Add JD button */}
                    <button
                      onClick={handleAddJdFile}
                      disabled={anyAnalyzing}
                      className="px-3 py-2 bg-gray-700 hover:bg-gray-600 text-gray-200 rounded-lg text-sm font-medium transition-colors disabled:opacity-50 flex items-center gap-2"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                      </svg>
                      Add JD File(s)
                    </button>

                    {jdEntries.length === 0 && (
                      <div className="text-center text-gray-500 text-xs py-4">
                        Upload one or more job descriptions to get started
                      </div>
                    )}

                    {/* JD entries list */}
                    {jdEntries.map((entry) => {
                      const inputs = newSkillInputs[entry.id] || { required: '', preferred: '' };
                      const isExpanded = activeJdId === entry.id;
                      const hasResults = entry.results && entry.results.length > 0;

                      return (
                        <div key={entry.id} className={`rounded-lg border transition-colors ${isExpanded ? 'border-blue-500/50 bg-gray-900/80' : 'border-gray-600 bg-gray-900/30'}`}>
                          {/* JD header - always visible */}
                          <div
                            className="flex items-center justify-between p-2.5 cursor-pointer"
                            onClick={() => setActiveJdId(isExpanded ? null : entry.id)}
                          >
                            <div className="flex items-center gap-2 min-w-0 flex-1">
                              <svg className="w-3.5 h-3.5 text-emerald-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                              </svg>
                              <span className="text-xs text-gray-200 font-medium truncate">{entry.fileName || 'Pasted JD'}</span>
                              {entry.analyzing && (
                                <div className="w-3 h-3 border border-blue-400 border-t-transparent rounded-full animate-spin flex-shrink-0" />
                              )}
                              {entry.requirements && !entry.analyzing && (
                                <span className="text-[10px] text-emerald-400 flex-shrink-0">
                                  {entry.requirements.required_skills?.length || 0} skills
                                </span>
                              )}
                              {hasResults && (
                                <span className="text-[10px] text-blue-400 flex-shrink-0">
                                  Top: {entry.results[0]?.score || 0}%
                                </span>
                              )}
                            </div>
                            <div className="flex items-center gap-1 flex-shrink-0">
                              <svg className={`w-3 h-3 text-gray-400 transition-transform ${isExpanded ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                              </svg>
                              <button
                                onClick={(e) => { e.stopPropagation(); handleRemoveJd(entry.id); }}
                                className="p-1 hover:bg-gray-700 rounded text-gray-500 hover:text-red-400"
                                title="Remove JD"
                              >
                                <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                                </svg>
                              </button>
                            </div>
                          </div>

                          {/* Expanded view with skills */}
                          {isExpanded && entry.requirements && !entry.analyzing && (
                            <div className="px-2.5 pb-2.5 space-y-2">
                              {/* Required Skills */}
                              <div>
                                <div className="text-[10px] text-emerald-400 mb-1">Required ({entry.requirements.required_skills?.length || 0}):</div>
                                <div className="flex flex-wrap gap-1 mb-1">
                                  {(entry.requirements.required_skills || []).map((skill: string, i: number) => (
                                    <span key={i} className="px-1.5 py-0.5 bg-emerald-500/20 text-emerald-300 rounded text-[10px] flex items-center gap-0.5">
                                      {skill}
                                      <button onClick={() => removeSkill(entry.id, 'required', i)} className="hover:text-white text-emerald-500 text-[9px]">&times;</button>
                                    </span>
                                  ))}
                                </div>
                                <div className="flex gap-1">
                                  <input
                                    type="text"
                                    value={inputs.required}
                                    onChange={(e) => updateSkillInput(entry.id, 'required', e.target.value)}
                                    onKeyDown={(e) => e.key === 'Enter' && addSkill(entry.id, 'required')}
                                    placeholder="Add skill..."
                                    className="flex-1 bg-gray-800 border border-gray-600 text-gray-100 rounded px-1.5 py-0.5 text-[10px] focus:outline-none focus:border-emerald-500 placeholder-gray-500"
                                  />
                                  <button onClick={() => addSkill(entry.id, 'required')} disabled={!inputs.required.trim()} className="px-1.5 py-0.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded text-[10px] disabled:opacity-30">+</button>
                                </div>
                              </div>

                              {/* Preferred Skills */}
                              <div>
                                <div className="text-[10px] text-blue-400 mb-1">Preferred ({entry.requirements.preferred_skills?.length || 0}):</div>
                                <div className="flex flex-wrap gap-1 mb-1">
                                  {(entry.requirements.preferred_skills || []).map((skill: string, i: number) => (
                                    <span key={i} className="px-1.5 py-0.5 bg-blue-500/20 text-blue-300 rounded text-[10px] flex items-center gap-0.5">
                                      {skill}
                                      <button onClick={() => removeSkill(entry.id, 'preferred', i)} className="hover:text-white text-blue-500 text-[9px]">&times;</button>
                                    </span>
                                  ))}
                                </div>
                                <div className="flex gap-1">
                                  <input
                                    type="text"
                                    value={inputs.preferred}
                                    onChange={(e) => updateSkillInput(entry.id, 'preferred', e.target.value)}
                                    onKeyDown={(e) => e.key === 'Enter' && addSkill(entry.id, 'preferred')}
                                    placeholder="Add skill..."
                                    className="flex-1 bg-gray-800 border border-gray-600 text-gray-100 rounded px-1.5 py-0.5 text-[10px] focus:outline-none focus:border-blue-500 placeholder-gray-500"
                                  />
                                  <button onClick={() => addSkill(entry.id, 'preferred')} disabled={!inputs.preferred.trim()} className="px-1.5 py-0.5 bg-blue-600 hover:bg-blue-500 text-white rounded text-[10px] disabled:opacity-30">+</button>
                                </div>
                              </div>
                            </div>
                          )}

                          {/* Analyzing spinner */}
                          {isExpanded && entry.analyzing && (
                            <div className="px-2.5 pb-2.5">
                              <div className="bg-blue-500/10 border border-blue-500/30 rounded p-2 flex items-center gap-2">
                                <div className="w-3 h-3 border border-blue-400 border-t-transparent rounded-full animate-spin" />
                                <span className="text-[10px] text-blue-400">Analyzing with AI...</span>
                              </div>
                            </div>
                          )}
                        </div>
                      );
                    })}

                    {/* Options */}
                    <div className="space-y-2 bg-gray-900/50 rounded-lg p-3">
                      <label className="flex items-center gap-2 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={useLlmForJd}
                          onChange={(e) => setUseLlmForJd(e.target.checked)}
                          disabled={!llmEnabled}
                          className="w-4 h-4 rounded border-gray-600 bg-gray-900 cursor-pointer disabled:opacity-50"
                        />
                        <span className={`text-sm ${llmEnabled ? 'text-gray-200' : 'text-gray-500'}`}>
                          Use AI for JD Analysis {!llmEnabled && '(API key required)'}
                        </span>
                      </label>

                      <label className="flex items-center gap-2 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={useDeepEval}
                          onChange={(e) => setUseDeepEval(e.target.checked)}
                          disabled={!llmEnabled}
                          className="w-4 h-4 rounded border-gray-600 bg-gray-900 cursor-pointer disabled:opacity-50"
                        />
                        <span className={`text-sm ${llmEnabled ? 'text-gray-200' : 'text-gray-500'}`}>
                          AI Contextual Ranking {!llmEnabled ? '(API key required)' : `(~${Math.ceil(topN * 4 / 3) * jdEntries.length} calls, recommended)`}
                        </span>
                      </label>

                      <label className="flex items-center gap-2 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={useLlm}
                          onChange={(e) => setUseLlm(e.target.checked)}
                          disabled={!llmEnabled}
                          className="w-4 h-4 rounded border-gray-600 bg-gray-900 cursor-pointer disabled:opacity-50"
                        />
                        <span className={`text-sm ${llmEnabled ? 'text-gray-200' : 'text-gray-500'}`}>
                          Use LLM for explanations
                        </span>
                      </label>

                      <div className="flex items-center gap-2">
                        <span className="text-sm text-gray-400">Show Top:</span>
                        <select
                          value={topN}
                          onChange={(e) => setTopN(parseInt(e.target.value))}
                          className="bg-gray-700 border border-gray-600 rounded px-2 py-1 text-sm text-gray-100 focus:outline-none focus:border-blue-500"
                        >
                          <option value={5}>5</option>
                          <option value={10}>10</option>
                        </select>
                      </div>
                    </div>

                    <button
                      onClick={handleRankResumes}
                      disabled={!canRank}
                      className="w-full px-4 py-3 bg-gradient-to-r from-blue-600 to-cyan-600 hover:from-blue-500 hover:to-cyan-500 text-white rounded-lg font-semibold transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2 shadow-lg"
                    >
                      {ranking && <div className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin" />}
                      {ranking
                        ? `Processing ${fileCount} Resume${fileCount !== 1 ? 's' : ''} x ${jdEntries.length} JD${jdEntries.length !== 1 ? 's' : ''}...`
                        : `Rank ${fileCount > 0 ? fileCount : ''} Resume${fileCount !== 1 ? 's' : ''} (${jdEntries.length} JD${jdEntries.length !== 1 ? 's' : ''})`
                      }
                    </button>

                    {rankError && (
                      <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-3">
                        <div className="text-red-400 text-sm">{rankError}</div>
                      </div>
                    )}
                  </div>
                </div>

                {/* Panel C: Results (grouped by JD) */}
                <div className="bg-gray-800 rounded-lg border border-gray-700 p-4 flex flex-col">
                  <h2 className="text-sm font-semibold text-gray-100 mb-3 flex items-center gap-2">
                    <span className="w-5 h-5 rounded bg-blue-600 flex items-center justify-center text-xs text-white">3</span>
                    Results
                  </h2>

                  {/* JD tabs for results */}
                  {jdEntries.length > 1 && jdEntries.some(e => e.results?.length > 0) && (
                    <div className="flex gap-1 mb-3 overflow-x-auto pb-1">
                      {jdEntries.filter(e => e.results?.length > 0).map((entry) => (
                        <button
                          key={entry.id}
                          onClick={() => setActiveJdId(entry.id)}
                          className={`px-2.5 py-1 rounded text-xs whitespace-nowrap transition-colors ${
                            activeJdId === entry.id
                              ? 'bg-blue-600 text-white'
                              : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                          }`}
                        >
                          {entry.fileName || 'JD'}
                        </button>
                      ))}
                    </div>
                  )}

                  {/* Active JD label */}
                  {activeJdEntry && activeResults.length > 0 && (
                    <div className="text-xs text-gray-400 mb-2">
                      Top {topN} for: <span className="text-blue-400 font-medium">{activeJdEntry.fileName || 'Pasted JD'}</span>
                    </div>
                  )}

                  <div className="flex-1 overflow-auto space-y-3">
                    {activeResults.length === 0 && !ranking && (
                      <div className="text-center text-gray-400 text-sm py-8">
                        Results will appear here after ranking
                      </div>
                    )}

                    {ranking && (
                      <div className="flex items-center justify-center py-8">
                        <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
                      </div>
                    )}

                    {activeResults.map((candidate: any, idx: number) => (
                      <div
                        key={idx}
                        className={`rounded-lg border p-4 ${getScoreBg(candidate.score)}`}
                      >
                        {/* Header with name and score */}
                        <div className="flex items-start justify-between mb-2">
                          <div className="flex-1">
                            <div className="text-gray-100 font-semibold text-sm">
                              #{idx + 1} {candidate.candidate_name}
                            </div>
                            <div className="text-gray-400 text-xs truncate">{candidate.file_name}</div>
                          </div>
                          <div className={`text-2xl font-bold ${getScoreColor(candidate.score)}`}>
                            {candidate.score}
                          </div>
                        </div>

                        {/* Section score breakdown */}
                        {(candidate.section_scores || candidate.llm_scores) && (
                          <div className="mb-3 space-y-1.5">
                            {(() => {
                              const scores = candidate.llm_scores || candidate.section_scores;
                              const isLlm = !!candidate.llm_scores;
                              const dimensions = [
                                { key: 'projects', label: 'Projects', color: 'bg-purple-500', val: isLlm ? scores.projects?.score : Math.round((scores.projects_score || 0) * 100), reasoning: isLlm ? scores.projects?.reasoning : null },
                                { key: 'experience', label: 'Experience', color: 'bg-cyan-500', val: isLlm ? scores.experience?.score : Math.round((scores.experience_score || 0) * 100), reasoning: isLlm ? scores.experience?.reasoning : null },
                                { key: 'certifications', label: 'Certs', color: 'bg-amber-500', val: isLlm ? scores.certifications?.score : Math.round((scores.certifications_score || 0) * 100), reasoning: isLlm ? scores.certifications?.reasoning : null },
                                { key: 'skills', label: 'Skills', color: 'bg-emerald-500', val: isLlm ? scores.skills?.score : Math.round((scores.skills_score || 0) * 100), reasoning: isLlm ? scores.skills?.reasoning : null },
                              ];
                              return dimensions.map((dim) => (
                                <div key={dim.key} className="flex items-center gap-2">
                                  <span className="text-[10px] text-gray-400 w-16 text-right">{dim.label}</span>
                                  <div className="flex-1 h-2 bg-gray-700 rounded-full overflow-hidden">
                                    <div className={`h-full ${dim.color} rounded-full transition-all`} style={{ width: `${dim.val}%` }} />
                                  </div>
                                  <span className="text-[10px] text-gray-300 w-8">{dim.val}%</span>
                                  {dim.reasoning && <span className="text-[9px] text-gray-500 truncate max-w-[120px]" title={dim.reasoning}>{dim.reasoning}</span>}
                                </div>
                              ));
                            })()}
                          </div>
                        )}

                        {/* Legacy score breakdown (fallback) */}
                        {!candidate.section_scores && !candidate.llm_scores && (
                          <div className="flex gap-4 text-xs text-gray-400 mb-3">
                            <span>Similarity: {Math.round(candidate.similarity * 100)}%</span>
                            <span>Match: {Math.round(candidate.keyword_coverage * 100)}%</span>
                          </div>
                        )}

                        {/* Required Skills - Matched */}
                        {candidate.matched_required && candidate.matched_required.length > 0 && (
                          <div className="mb-2">
                            <div className="text-xs text-emerald-400 mb-1 font-medium">Matched Required:</div>
                            <div className="flex flex-wrap gap-1">
                              {candidate.matched_required.slice(0, 8).map((kw: string, i: number) => (
                                <span key={i} className="px-2 py-0.5 bg-emerald-500/20 text-emerald-400 rounded text-xs">
                                  {kw}
                                </span>
                              ))}
                              {candidate.matched_required.length > 8 && (
                                <span className="px-2 py-0.5 text-emerald-400 text-xs">
                                  +{candidate.matched_required.length - 8}
                                </span>
                              )}
                            </div>
                          </div>
                        )}

                        {/* Required Skills - Missing */}
                        {candidate.missing_required && candidate.missing_required.length > 0 && (
                          <div className="mb-2">
                            <div className="text-xs text-red-400 mb-1 font-medium">Missing Required:</div>
                            <div className="flex flex-wrap gap-1">
                              {candidate.missing_required.slice(0, 5).map((kw: string, i: number) => (
                                <span key={i} className="px-2 py-0.5 bg-red-500/20 text-red-400 rounded text-xs">
                                  {kw}
                                </span>
                              ))}
                              {candidate.missing_required.length > 5 && (
                                <span className="px-2 py-0.5 text-red-400 text-xs">
                                  +{candidate.missing_required.length - 5}
                                </span>
                              )}
                            </div>
                          </div>
                        )}

                        {/* Preferred Skills - Matched */}
                        {candidate.matched_preferred && candidate.matched_preferred.length > 0 && (
                          <div className="mb-2">
                            <div className="text-xs text-blue-400 mb-1 font-medium">Preferred Matched:</div>
                            <div className="flex flex-wrap gap-1">
                              {candidate.matched_preferred.slice(0, 6).map((kw: string, i: number) => (
                                <span key={i} className="px-2 py-0.5 bg-blue-500/20 text-blue-400 rounded text-xs">
                                  {kw}
                                </span>
                              ))}
                              {candidate.matched_preferred.length > 6 && (
                                <span className="px-2 py-0.5 text-blue-400 text-xs">
                                  +{candidate.matched_preferred.length - 6}
                                </span>
                              )}
                            </div>
                          </div>
                        )}

                        {/* Explanation */}
                        <div className="text-xs text-gray-200 mb-3 leading-relaxed">
                          {candidate.explanation}
                        </div>

                        {/* Open button */}
                        <button
                          onClick={() => handleOpenFile(candidate.file_path)}
                          className="w-full px-3 py-2 bg-gray-700 hover:bg-gray-600 text-gray-100 rounded-lg text-sm font-medium transition-colors flex items-center justify-center gap-2"
                        >
                          Open Resume
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

// Export for ContextUI
window.ResumeRankerWindow = ResumeRankerWindow;
