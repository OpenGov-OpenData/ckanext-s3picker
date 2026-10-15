(function () {
  'use strict';

  var root = document.getElementById('s3picker');
  if (!root) {
    return;
  }

  var browseUrl = root.dataset.browseUrl;
  var matchesUrl = root.dataset.matchesUrl;
  var downloadUrl = root.dataset.downloadUrl;
  var maxFiles = parseInt(root.dataset.maxFiles, 10);
  var isPrivate = root.dataset.private === 'true';
  var MAX_SHOWN_LINKS = 100;
  var tree = root.querySelector('.s3picker-tree');
  var searchInput = root.querySelector('.s3picker-search');
  var searchResults = root.querySelector('.s3picker-search-results');
  var totalEl = root.querySelector('.s3picker-total');
  var clearBtn = root.querySelector('.s3picker-clear');
  var getLinksBtn = root.querySelector('.s3picker-get-links');
  var messageEl = root.querySelector('.s3picker-message');
  var resultsEl = root.querySelector('.s3picker-results');

  // id -> {path, size}; folder path -> {count, size}. '' is the whole catalog.
  var selectedFiles = new Map();
  var selectedFolders = new Map();
  var searchSeq = 0;

  function formatBytes(n) {
    var units = ['B', 'KB', 'MB', 'GB', 'TB'];
    var i = 0;
    while (n >= 1024 && i < units.length - 1) {
      n /= 1024;
      i++;
    }
    return i === 0 ? n + ' B' : n.toFixed(1) + ' ' + units[i];
  }

  function plural(n, word) {
    return n.toLocaleString() + ' ' + word + (n === 1 ? '' : 's');
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) {
      node.className = className;
    }
    if (text !== undefined) {
      node.textContent = text;
    }
    return node;
  }

  function isUnder(path, folder) {
    return folder === '' || path === folder || path.indexOf(folder + '/') === 0;
  }

  function ancestorSelected(path, strict) {
    var found = false;
    selectedFolders.forEach(function (_, folder) {
      if (isUnder(path, folder) && !(strict && folder === path)) {
        found = true;
      }
    });
    return found;
  }

  function showMessage(text, kind) {
    if (!text) {
      messageEl.hidden = true;
      return;
    }
    messageEl.className = 's3picker-message alert alert-' + (kind || 'info');
    messageEl.textContent = text;
    messageEl.hidden = false;
  }

  function handleResponse(resp) {
    return resp.json().catch(function () { return {}; }).then(function (body) {
      if (!resp.ok) {
        throw new Error(body.error || 'Request failed (' + resp.status + ')');
      }
      return body;
    });
  }

  function getJSON(params, base) {
    var url = new URL(base || browseUrl, window.location.href);
    Object.keys(params).forEach(function (key) {
      url.searchParams.set(key, params[key]);
    });
    return fetch(url.toString(), {
      credentials: 'same-origin',
      headers: {Accept: 'application/json'}
    }).then(handleResponse);
  }

  function csrfHeaders() {
    // CKAN >= 2.10 exposes the CSRF token via meta tags; 2.9 has none.
    var fieldMeta = document.querySelector('meta[name="csrf_field_name"]');
    if (!fieldMeta) {
      return {};
    }
    var tokenMeta = document.querySelector('meta[name="' + fieldMeta.content + '"]');
    return tokenMeta ? {'X-CSRFToken': tokenMeta.content} : {};
  }

  // ---- rendering --------------------------------------------------------

  function checkbox(label) {
    var cb = el('input', 's3picker-check');
    cb.type = 'checkbox';
    cb.setAttribute('aria-label', label);
    return cb;
  }

  function folderNode(dir, isRoot) {
    var li = el('li');
    li.dataset.kind = 'folder';
    li.dataset.path = dir.path;
    li.dataset.count = dir.file_count;
    li.dataset.size = dir.size;
    li.setAttribute('role', 'treeitem');
    li.setAttribute('aria-expanded', 'false');

    var row = el('div', 's3picker-row');
    var toggle = el('button', 's3picker-toggle', '▸');
    toggle.type = 'button';
    toggle.setAttribute('aria-label', 'Expand ' + dir.name);
    var name = isRoot ? dir.name + ' (entire catalog)' : dir.name + '/';
    var cb = checkbox('Select folder ' + (dir.path || dir.name));
    var label = el('label', null, name);
    label.prepend(cb);
    row.appendChild(toggle);
    row.appendChild(label);
    row.appendChild(el('span', 's3picker-meta',
      plural(dir.file_count, 'file') + ' · ' + formatBytes(dir.size)));
    li.appendChild(row);

    toggle.addEventListener('click', function () {
      toggleFolderOpen(li, toggle);
    });
    return li;
  }

  function fileNode(file, showFullPath) {
    var li = el('li');
    li.dataset.kind = 'file';
    li.dataset.id = file.id;
    li.dataset.path = file.path;
    li.dataset.size = file.size;
    li.setAttribute('role', 'treeitem');

    var row = el('div', 's3picker-row');
    row.appendChild(el('span', 's3picker-toggle'));
    var cb = checkbox('Select file ' + file.path);
    var label = el('label', null, showFullPath ? file.path : file.name);
    label.prepend(cb);
    row.appendChild(label);
    row.appendChild(el('span', 's3picker-meta', formatBytes(file.size)));
    li.appendChild(row);
    return li;
  }

  function appendPage(list, params, showFullPath) {
    var loading = el('li', 's3picker-meta', 'Loading…');
    list.appendChild(loading);
    return getJSON(params).then(function (data) {
      loading.remove();
      data.dirs.forEach(function (dir) {
        list.appendChild(folderNode(dir, false));
      });
      data.files.forEach(function (file) {
        list.appendChild(fileNode(file, showFullPath));
      });
      if (!data.dirs.length && !data.files.length && data.page === 0) {
        list.appendChild(el('li', 's3picker-meta',
          params.q ? 'No matching files.' : 'Empty folder.'));
      }
      if (data.has_more) {
        var item = el('li');
        var more = el('button', 'btn btn-default btn-xs s3picker-more',
          'Load more (' + (data.total - (data.page + 1) * data.page_size).toLocaleString() + ' remaining)');
        more.type = 'button';
        more.addEventListener('click', function () {
          item.remove();
          var next = Object.assign({}, params, {page: data.page + 1});
          appendPage(list, next, showFullPath);
        });
        item.appendChild(more);
        list.appendChild(item);
      }
      syncCheckboxes();
      return data;
    }).catch(function (err) {
      loading.textContent = 'Could not load: ' + err.message;
    });
  }

  function toggleFolderOpen(li, toggle) {
    var open = li.getAttribute('aria-expanded') === 'true';
    var children = li.querySelector(':scope > ul');
    if (open) {
      li.setAttribute('aria-expanded', 'false');
      toggle.textContent = '▸';
      if (children) {
        children.hidden = true;
      }
      return;
    }
    li.setAttribute('aria-expanded', 'true');
    toggle.textContent = '▾';
    if (children) {
      children.hidden = false;
      return;
    }
    children = el('ul');
    children.setAttribute('role', 'group');
    li.appendChild(children);
    appendPage(children, {path: li.dataset.path, page: 0}, false);
  }

  // ---- selection --------------------------------------------------------

  function syncCheckboxes() {
    root.querySelectorAll('li[data-kind]').forEach(function (li) {
      var cb = li.querySelector(':scope > .s3picker-row .s3picker-check');
      var path = li.dataset.path;
      var covered;
      if (li.dataset.kind === 'folder') {
        covered = ancestorSelected(path, true);
        cb.checked = covered || selectedFolders.has(path);
      } else {
        covered = ancestorSelected(path, false);
        cb.checked = covered || selectedFiles.has(li.dataset.id);
      }
      cb.disabled = covered;
      li.querySelector(':scope > .s3picker-row').classList.toggle('s3picker-selected', cb.checked);
    });
  }

  function updateTotals() {
    var count = 0;
    var size = 0;
    selectedFolders.forEach(function (info) {
      count += info.count;
      size += info.size;
    });
    selectedFiles.forEach(function (info) {
      count += 1;
      size += info.size;
    });
    var over = count > maxFiles;
    totalEl.textContent = count === 0 ? 'No files selected.' :
      plural(count, 'file') + ' (' + formatBytes(size) + ') selected' +
      (over ? ' — exceeds the ' + maxFiles.toLocaleString() + '-file limit per request.' : '.');
    totalEl.classList.toggle('s3picker-over-limit', over);
    getLinksBtn.disabled = count === 0 || over;
    clearBtn.disabled = count === 0;
  }

  function selectFolder(path, info) {
    selectedFolders.forEach(function (_, folder) {
      if (folder !== path && isUnder(folder, path)) {
        selectedFolders.delete(folder);
      }
    });
    selectedFiles.forEach(function (file, id) {
      if (isUnder(file.path, path)) {
        selectedFiles.delete(id);
      }
    });
    selectedFolders.set(path, info);
  }

  root.addEventListener('change', function (event) {
    var cb = event.target;
    if (!cb.classList.contains('s3picker-check')) {
      return;
    }
    var li = cb.closest('li');
    if (li.dataset.kind === 'folder') {
      if (cb.checked) {
        selectFolder(li.dataset.path, {
          count: parseInt(li.dataset.count, 10),
          size: parseInt(li.dataset.size, 10)
        });
      } else {
        selectedFolders.delete(li.dataset.path);
      }
    } else if (cb.checked) {
      selectedFiles.set(li.dataset.id, {
        path: li.dataset.path,
        size: parseInt(li.dataset.size, 10)
      });
    } else {
      selectedFiles.delete(li.dataset.id);
    }
    syncCheckboxes();
    updateTotals();
  });

  clearBtn.addEventListener('click', function () {
    selectedFiles.clear();
    selectedFolders.clear();
    syncCheckboxes();
    updateTotals();
  });

  // ---- search -----------------------------------------------------------

  var searchTimer = null;
  searchInput.addEventListener('input', function () {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(runSearch, 300);
  });

  function runSearch() {
    var q = searchInput.value.trim();
    var seq = ++searchSeq;
    searchResults.textContent = '';
    if (!q) {
      searchResults.hidden = true;
      tree.hidden = false;
      return;
    }
    tree.hidden = true;
    searchResults.hidden = false;
    var list = el('ul');
    searchResults.appendChild(list);
    appendPage(list, {q: q, page: 0}, true).then(function (data) {
      if (seq !== searchSeq) {
        list.remove();
      } else if (data && data.total > 0) {
        searchResults.insertBefore(matchesBar(q, data), list);
      }
    });
  }

  function matchesBar(q, data) {
    var bar = el('div', 's3picker-matches');
    var matchWord = data.total.toLocaleString() + (data.total === 1 ? ' match' : ' matches');
    var summary = el('span', null, matchWord + ' (' + formatBytes(data.total_size) + ')');
    var button = el('button', 'btn btn-default btn-xs', 'Select all ' + matchWord);
    button.type = 'button';
    var status = el('span', 's3picker-meta');
    status.setAttribute('aria-live', 'polite');
    if (data.total > maxFiles) {
      button.disabled = true;
      status.textContent = 'Too many matches to select at once (limit ' +
        maxFiles.toLocaleString() + '). Narrow your search.';
    }
    button.addEventListener('click', function () {
      selectAllMatches(q, button, status);
    });
    bar.appendChild(summary);
    bar.appendChild(button);
    bar.appendChild(status);
    return bar;
  }

  function selectAllMatches(q, button, status) {
    button.disabled = true;
    status.textContent = 'Selecting\u2026';
    getJSON({q: q}, matchesUrl).then(function (data) {
      if (data.total > data.max_files) {
        status.textContent = 'Too many matches to select at once (limit ' +
          data.max_files.toLocaleString() + '). Narrow your search.';
        return;
      }
      var added = 0;
      data.files.forEach(function (f) {
        if (!ancestorSelected(f.path, false) && !selectedFiles.has(f.id)) {
          selectedFiles.set(f.id, {path: f.path, size: f.size});
          added++;
        }
      });
      syncCheckboxes();
      updateTotals();
      status.textContent = added === data.files.length ?
        'Selected ' + plural(added, 'file') + '.' :
        'Selected ' + plural(added, 'more file') + ' (the rest were already selected).';
      button.disabled = false;
    }).catch(function (err) {
      status.textContent = 'Could not select matches: ' + err.message;
      button.disabled = false;
    });
  }

  // ---- download links ---------------------------------------------------

  getLinksBtn.addEventListener('click', function () {
    getLinksBtn.disabled = true;
    showMessage('Generating download links…', 'info');
    resultsEl.hidden = true;
    var headers = Object.assign({
      'Content-Type': 'application/json',
      Accept: 'application/json'
    }, csrfHeaders());
    fetch(downloadUrl, {
      method: 'POST',
      credentials: 'same-origin',
      headers: headers,
      body: JSON.stringify({
        files: Array.from(selectedFiles.keys()),
        folders: Array.from(selectedFolders.keys())
      })
    }).then(handleResponse).then(function (data) {
      showMessage(null);
      renderResults(data);
    }).catch(function (err) {
      showMessage(err.message, 'danger');
    }).then(updateTotals);
  });

  // wget -x recreates the URL's directories; --cut-dirs drops the ones before
  // the file's own path ([root path]/custom-downloads/<catalog>/file).
  function wgetCutDirs(file) {
    var urlSegments = new URL(file.url, window.location.href).pathname.split('/').filter(Boolean).length;
    return urlSegments - file.path.split('/').length;
  }

  function downloadHelp(data) {
    var box = el('div', 's3picker-help');
    box.appendChild(el('h4', null, 'How to download many files'));
    if (isPrivate) {
      box.appendChild(el('p', null,
        'This catalog is private, so downloads need your CKAN API token (API Tokens tab of your user profile). ' +
        'Click "Save URL list" below to download urls.txt, then in a terminal in the same folder run:'));
      box.appendChild(el('pre', 's3picker-command',
        'while read u; do curl -fL --create-dirs -o "${u#*/file/}" -H "Authorization: YOUR_API_TOKEN" "$u"; done < urls.txt'));
      box.appendChild(el('p', null,
        'Use curl, not wget: wget also sends the token to Amazon S3, which rejects the download.'));
    } else {
      box.appendChild(el('p', null,
        'Click "Save URL list" below to download urls.txt. ' +
        'Move it into the folder where the files should go, open a terminal there, and run:'));
      box.appendChild(el('pre', 's3picker-command',
        'wget -x -nH --cut-dirs=' + wgetCutDirs(data.files[0]) + ' -i urls.txt'));
      box.appendChild(el('p', null,
        'This keeps the folder structure shown above. A download manager such as uGet can import urls.txt instead.'));
    }
    return box;
  }

  function renderResults(data) {
    var urls = data.files.map(function (f) { return f.url; });
    resultsEl.textContent = '';
    resultsEl.appendChild(el('h3', null, plural(data.count, 'download link') +
      ' (' + formatBytes(data.total_size) + ')'));
    resultsEl.appendChild(el('p', 's3picker-hint',
      'Each link checks access when opened and then starts the download.'));
    resultsEl.appendChild(downloadHelp(data));

    var actions = el('div', 's3picker-result-actions');
    var save = el('button', 'btn btn-default', 'Save URL list');
    save.type = 'button';
    save.addEventListener('click', function () {
      var blob = new Blob([urls.join('\n') + '\n'], {type: 'text/plain'});
      var href = URL.createObjectURL(blob);
      var a = document.createElement('a');
      a.href = href;
      a.download = 'urls.txt';
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(href);
    });

    actions.appendChild(save);
    resultsEl.appendChild(actions);

    var list = el('ol');
    data.files.slice(0, MAX_SHOWN_LINKS).forEach(function (f) {
      var li = el('li');
      var a = el('a', null, f.path);
      a.href = f.url;
      a.rel = 'noopener';
      li.appendChild(a);
      li.appendChild(document.createTextNode(' '));
      li.appendChild(el('span', 's3picker-meta', formatBytes(f.size)));
      list.appendChild(li);
    });
    resultsEl.appendChild(list);
    if (data.files.length > MAX_SHOWN_LINKS) {
      resultsEl.appendChild(el('p', 's3picker-hint',
        'Showing the first ' + MAX_SHOWN_LINKS + ' of ' + data.files.length.toLocaleString() +
        ' links. "Save URL list" includes all of them.'));
    }
    resultsEl.hidden = false;
    resultsEl.scrollIntoView({behavior: 'smooth', block: 'start'});
  }

  // ---- init -------------------------------------------------------------

  var rootList = el('ul');
  var rootNode = folderNode({
    name: root.dataset.rootName,
    path: '',
    file_count: parseInt(root.dataset.rootCount, 10),
    size: parseInt(root.dataset.rootSize, 10)
  }, true);
  rootList.appendChild(rootNode);
  tree.appendChild(rootList);
  toggleFolderOpen(rootNode, rootNode.querySelector('.s3picker-toggle'));
  updateTotals();
})();
