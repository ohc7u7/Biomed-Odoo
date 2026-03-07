/* BioMed v2.5 — Website prescription analysis */
(function() {
    'use strict';

    var ANALISIS_TIMEOUT_MS = 90000; // 90 segundos

    function initBiomed() {
        var block = document.getElementById('biomed-receta-block');
        if (!block) return;

        var productId   = block.getAttribute('data-product-id');
        var fileInput   = document.getElementById('biomed-file-input');
        var uploadZone  = document.getElementById('biomed-upload-zone');
        var previewWrap = document.getElementById('biomed-preview-wrap');
        var previewImg  = document.getElementById('biomed-preview-img');
        var removeBtn   = document.getElementById('biomed-remove-btn');
        var condInput   = document.getElementById('biomed-condiciones');
        var analizarBtn = document.getElementById('biomed-analizar-btn');
        var loadingDiv  = document.getElementById('biomed-loading');
        var resultDiv   = document.getElementById('biomed-resultado');
        var reanalBtn   = document.getElementById('biomed-reanalizar-btn');
        var nuevaDiv    = document.getElementById('biomed-nueva-receta');

        if (!fileInput) return;
        var imgBase64 = null;

        if (reanalBtn && nuevaDiv) {
            reanalBtn.addEventListener('click', function() {
                nuevaDiv.style.display = 'block';
                reanalBtn.style.display = 'none';
            });
        }

        if (uploadZone) {
            uploadZone.addEventListener('click', function(e) {
                if (e.target === removeBtn) return;
                fileInput.click();
            });
            uploadZone.addEventListener('dragover', function(e) {
                e.preventDefault();
                uploadZone.classList.add('dragover');
            });
            uploadZone.addEventListener('dragleave', function() {
                uploadZone.classList.remove('dragover');
            });
            uploadZone.addEventListener('drop', function(e) {
                e.preventDefault();
                uploadZone.classList.remove('dragover');
                if (e.dataTransfer.files[0]) readFile(e.dataTransfer.files[0]);
            });
        }

        fileInput.addEventListener('change', function() {
            if (this.files[0]) readFile(this.files[0]);
        });

        if (removeBtn) {
            removeBtn.addEventListener('click', function(e) {
                e.stopPropagation();
                imgBase64 = null;
                fileInput.value = '';
                if (previewWrap) previewWrap.style.display = 'none';
                if (uploadZone) uploadZone.style.display = 'block';
                if (analizarBtn) analizarBtn.disabled = true;
                if (resultDiv) resultDiv.innerHTML = '';
            });
        }

        function readFile(file) {
            // Comprimir si es muy grande
            var reader = new FileReader();
            reader.onload = function(e) {
                var img = new Image();
                img.onload = function() {
                    // Redimensionar a máximo 800px para reducir tamaño
                    var canvas = document.createElement('canvas');
                    var MAX = 800;
                    var w = img.width, h = img.height;
                    if (w > MAX || h > MAX) {
                        if (w > h) { h = Math.round(h * MAX / w); w = MAX; }
                        else       { w = Math.round(w * MAX / h); h = MAX; }
                    }
                    canvas.width = w;
                    canvas.height = h;
                    canvas.getContext('2d').drawImage(img, 0, 0, w, h);
                    var compressed = canvas.toDataURL('image/jpeg', 0.85);
                    imgBase64 = compressed.split(',')[1];
                    if (previewImg) previewImg.src = compressed;
                    if (previewWrap) previewWrap.style.display = 'block';
                    if (uploadZone) uploadZone.style.display = 'none';
                    if (analizarBtn) analizarBtn.disabled = false;
                    console.log('[BioMed] Imagen lista, tamaño b64:', imgBase64.length);
                };
                img.src = e.target.result;
            };
            reader.readAsDataURL(file);
        }

        if (analizarBtn) {
            analizarBtn.addEventListener('click', function() {
                if (!imgBase64) return;

                analizarBtn.disabled = true;
                if (loadingDiv) loadingDiv.style.display = 'block';
                if (resultDiv) resultDiv.innerHTML = '';

                var condiciones = condInput ? condInput.value.trim() : '';

                var controller = new AbortController();
                var timeoutId = setTimeout(function() {
                    controller.abort();
                }, ANALISIS_TIMEOUT_MS);

                console.log('[BioMed] Enviando a /biomed/analizar-receta, product_id=' + productId + ', img_len=' + imgBase64.length);

                fetch('/biomed/analizar-receta', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    signal: controller.signal,
                    body: JSON.stringify({
                        jsonrpc: '2.0',
                        method: 'call',
                        id: 1,
                        params: {
                            product_id: parseInt(productId),
                            imagen_b64: imgBase64,
                            condiciones: condiciones
                        }
                    })
                })
                .then(function(r) {
                    clearTimeout(timeoutId);
                    if (!r.ok) throw new Error('HTTP ' + r.status);
                    return r.json();
                })
                .then(function(data) {
                    if (loadingDiv) loadingDiv.style.display = 'none';
                    analizarBtn.disabled = false;

                    if (data.error) {
                        var msg = (data.error.data && data.error.data.message) || JSON.stringify(data.error);
                        console.error('[BioMed] JSON-RPC error:', msg);
                        if (resultDiv) resultDiv.innerHTML = '<div style="background:#f8d7da;border-left:4px solid #dc3545;padding:12px;border-radius:6px;color:#721c24;"><strong>Error:</strong> ' + msg + '</div>';
                        return;
                    }

                    var res = data.result || {};
                    console.log('[BioMed] Resultado: approved=' + res.approved + ' error=' + res.error);

                    if (res.error) {
                        if (resultDiv) resultDiv.innerHTML = '<div style="background:#f8d7da;border-left:4px solid #dc3545;padding:12px;border-radius:6px;color:#721c24;"><strong>Error:</strong> ' + res.error + '</div>';
                        return;
                    }

                    if (resultDiv) resultDiv.innerHTML = res.html_response || '';
                    if (res.approved) {
                        setTimeout(function() { window.location.reload(); }, 2500);
                    }
                })
                .catch(function(err) {
                    clearTimeout(timeoutId);
                    if (loadingDiv) loadingDiv.style.display = 'none';
                    analizarBtn.disabled = false;

                    var msg = err.name === 'AbortError'
                        ? 'Tiempo de espera agotado (90s). El servidor tardó demasiado.'
                        : 'Error de conexión: ' + err.message;
                    console.error('[BioMed] Error:', err.name, err.message);
                    if (resultDiv) resultDiv.innerHTML = '<div style="background:#f8d7da;border-left:4px solid #dc3545;padding:12px;border-radius:6px;color:#721c24;">' + msg + '</div>';
                });
            });
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initBiomed);
    } else {
        initBiomed();
    }
})();