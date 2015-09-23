# -*- coding: utf-8 -*-
from flask import jsonify, request, render_template, url_for, redirect
from flask.ext.babel import gettext as _
from datetime import datetime

from __init__ import __version__, app, logger, get_locale, \
    VALID_LANGUAGES, DEFAULT_USER_AGENT, MAX_TEXT_LENGTH
from utils import *

import requests
import json
import re
import nilsimsa  # Locality Sensitive Hash
import os
import sys
import yaml


@app.route('/longtext')
def longtext():
    return render_template('longtext.html')


@app.route('/backupdb')
def backupdb():
    """This is a temporary workaround. We shall figure out how to store
    data in a relational database directly from the GAE. The problem we had
    was that we could not use psycopg2 package on GAE."""

    # NOTE: Minimal protection against malicious parties...
    api_key = request.args.get('api_key')
    config = yaml.load(open('config.yml'))
    if api_key != config['api_key']:
        return 'Invalid API key', 401

    limit = int(request.args.get('limit', 1000))
    from corpus.models import CorpusRaw, ndb
    query = CorpusRaw.query()
    entries = query.fetch(limit)
    output = '\n'.join(['{}\t{}\t{}\t{}'.format(
        x.source_lang, x.target_lang, x.timestamp, x.raw) for x in entries])
    ndb.delete_multi([x.key for x in entries])
    return output


def __translate__(text, source, target, client='x',
                  user_agent=DEFAULT_USER_AGENT):
    """
    text: text to be translated
    source: source language
    target: target language
    """

    if source == target:
        return text

    if not re.match(r'Mozilla/\d+\.\d+ \(.*', user_agent):
        user_agent = 'Mozilla/5.0 (%s)' % user_agent

    headers = {
        'Referer': 'http://translate.google.com',
        'User-Agent': user_agent,
        'Content-Length': str(sys.getsizeof(text))
    }
    payload = {
        'client': client,
        'sl': source,
        'tl': target,
        'text': text,
    }
    url = 'http://translate.google.com/translate_a/t'

    req = requests.post(url, headers=headers, data=payload)

    if req.status_code != 200:
        raise HTTPException(
            ('Google Translate returned HTTP {}'.format(req.status_code)),
            req.status_code)

    if client == 'x':
        data = json.loads(req.text)

        try:
            sentences = data['sentences']
        except:
            sentences = data['results'][0]['sentences']

        result = ' '.join(map(lambda x: x['trans'], sentences))

        # Remove unneccessary white spaces
        return '\n'.join(map(lambda x: x.strip(), result.split('\n')))

    elif client == 't':
        return parse_javascript(req.text)

    else:
        raise Exception("Unsupported client '{}'".format(client))


#
# Request handlers
#
@app.route('/')
@app.route('/tr/<translation_id>')
def index(translation_id=None):

    if request.host == 'translator.suminb.com':
        return redirect('http://better-translator.com')

    """
    NOTE: Do not use HTTP GET parameters 'sl', 'tl', 'm' and 't'. These are
    reserved for special purposes.
    """
    user_agent = request.headers.get('User-Agent')
    is_android = 'Android' in user_agent
    is_iphone = 'iPhone' in user_agent
    is_msie = 'MSIE' in user_agent

    context = dict(
        version=__version__,
        locale=get_locale(),
        is_android=is_android,
        is_msie=is_msie,
        language_options=language_options_html(),
        debug=os.environ.get('DEBUG', None),
    )

    tresponse = None

    translation_id = translation_id or request.args.get('tr', None)

    #if translation_id != None:
    #    tresponse = TranslationResponse.fetch(id_b62=translation_id)

    if translation_id is not None and tresponse is None:
        return redirect(url_for('index'))

    if tresponse is not None:
        translation = tresponse.serialize()
        translation['original_text'] = tresponse.request.original_text
        #translation['translated_text_dictlink'] = link_dictionary(
        #translation['translated_text'], translation['source'], translation['target'])

        context['og_description'] = tresponse.request.original_text
        context['translation'] = json.dumps(translation)
    else:
        context['og_description'] = _('app-description-text')

    return render_template('index.html', **context)


@app.route('/locale', methods=['GET', 'POST'])
def set_locale():
    """Copied from https://github.com/lunant/lunant-web/blob/homepage/lunant/__init__.py"""  # noqa
    if request.method == 'GET':
        locale = request.args['locale']
    else:
        locale = request.form['locale']

    if request.referrer:
        dest = request.referrer
    else:
        dest = url_for('index')

    response = redirect(dest)
    response.set_cookie('locale', locale, 60 * 60 * 24 * 14)
    return response


@app.route('/languages')
@app.route('/v1.0/languages')
def languages():
    """Returns a list of supported languages."""
    locale = request.args['locale']
    langs = {k: _(v) for (k, v) in zip(VALID_LANGUAGES.keys(),
                                       VALID_LANGUAGES.values())}

    return jsonify(langs)


@app.route('/discuss')
def discuss():
    context = dict(
        version=__version__,
        locale=get_locale(),
    )
    return render_template('discuss.html', **context)


@app.route('/credits')
def credits():
    context = dict(
        version=__version__,
        locale=get_locale(),
    )
    return render_template('credits.html', **context)


@app.route('/statistics')
def statistics():
    if request.args.get('format') == 'json':
        from analytics import generate_output
        from flask import Response
        return Response(generate_output(), mimetype='application/json')
    else:
        context = dict(
            version=__version__,
            timestamp=datetime.now().strftime('%Y%m%d%H%M')
        )
        return render_template('statistics.html', **context)


@app.route('/v1.0/translate', methods=['POST'])
def translate_1_0():
    """
    :param sl: source language
    :type sl: string
    :param tl: target language
    :type tl: string
    :param m: mode ( 1 for normal, 2 for better )
    :type m: int
    :param t: text to be translated
    :type t: string

    Translates given text.

    **Example Request**:

    .. sourcecode:: http

        POST /v1.0/translate HTTP/1.1
        User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_8_2) AppleWebKit/537.22 (KHTML, like Gecko) Chrome/25.0.1364.99 Safari/537.22
        Host: 192.168.0.185:5000
        Accept: */*
        Content-Length: 57
        Content-Type: application/x-www-form-urlencoded

        sl=ko&tl=en&m=2&t=여러분이 몰랐던 구글 번역기

    **Example Response**

    .. sourcecode:: http

        HTTP/1.0 200 OK
        Content-Type: application/json
        Content-Length: 90
        Server: Werkzeug/0.8.3 Python/2.7.3
        Date: Wed, 10 Apr 2013 06:43:13 GMT

        {
          "translated_text": "Google translation that you did not know",
          "serial_b62": "0z19x",
          "intermediate_text": "\u7686\u3055\u3093\u304c\u77e5\u3089\u306a\u304b\u3063\u305fGoogle\u306e\u7ffb\u8a33"
        }

    **Example iOS Code using ILHTTPClient**

    ILHTTPClient: https://github.com/isaaclimdc/ILHTTPClient

    .. sourcecode:: objective-c

        ILHTTPClient *client = [ILHTTPClient clientWithBaseURL:@"http://translator.suminb.com/" showingHUDInView:self.view];
            NSDictionary *params = @{
                                        @"sl": @"en",
                                        @"tl": @"ko",
                                        @"m": @"2",
                                        @"t": @"Google translation that you did not know."
            };

            [client postPath:@"/v1.0/translate"
                  parameters:params
                 loadingText:@"Loading..."
                 successText:@"Success!"
               multiPartForm:^(id<AFMultipartFormData> formData) {
               }
                     success:^(AFHTTPRequestOperation *operation, NSString *response) {
                         NSLog(@"%@", response);
                     }
                     failure:^(AFHTTPRequestOperation *operation, NSError *error) {
                     }
            ];
    """  # noqa
    keys = ('t', 'm', 'sl', 'tl')
    text, mode, source, target = map(lambda k: request.form[k].strip(), keys)

    try:
        return jsonify(translate(text, mode, source, target))

    except HTTPException as e:
        return e.message, e.status_code

    except Exception as e:
        logger.exception(e)
        return str(e), 500


@app.route('/v1.1/translate', methods=['POST'])
def translate_1_1():
    """
    :param sl: source language
    :type sl: string
    :param tl: target language
    :type tl: string
    :param m: mode ( 1 for normal, 2 for better )
    :type m: int
    :param t: text to be translated
    :type t: string

    Translates given text.
    """
    keys = ('t', 'm', 'sl', 'tl')
    text, mode, source, target = map(lambda k: request.form[k].strip(), keys)

    try:
        payload = translate(text, mode, source, target)
        return jsonify(payload)

    except HTTPException as e:
        return e.message, e.status_code

    except Exception as e:
        logger.exception(e)
        return str(e), 500


@app.route('/v1.2/translate', methods=['POST'])
def translate_1_2():
    """
    :param sl: source language
    :type sl: string
    :param tl: target language
    :type tl: string
    :param m: mode ( 1 for normal, 2 for better )
    :type m: int
    :param t: text to be translated
    :type t: string

    Translates given text.
    """
    keys = ('t', 'm', 'sl', 'tl')
    text, mode, source, target = map(lambda k: request.form[k].strip(), keys)

    try:
        payload = translate(text, mode, source, target, 't')

        return jsonify(payload)

    except HTTPException as e:
        return e.message, e.status_code

    except Exception as e:
        logger.exception(e)
        return str(e), 500


def translate(text, mode, source, target, client='x'):

    if len(text) == 0:
        raise HTTPException('Text cannot be empty.', 400)

    if len(text) > MAX_TEXT_LENGTH:
        raise HTTPException('Text too long.', 413)

    if source == target:
        return dict(
            id=None,
            id_b62=None,
            intermediate_text=None,
            translated_text=text)

    if source not in VALID_LANGUAGES.keys():
        raise HTTPException('Invalid source language.', 400)
    if target not in VALID_LANGUAGES.keys():
        raise HTTPException('Invalid target language.', 400)

    original_text_hash = nilsimsa.Nilsimsa(text.encode('utf-8')).hexdigest()
    user_agent = request.headers.get('User-Agent')

    translated_raw = None
    translated_text = None
    intermediate_raw = None
    intermediate_text = None

    # NOTE: The following may be time consuming operations
    # FIXME: Refactor this code. Looks crappy.
    if mode == '1':
        if client == 't':
            translated_raw = __translate__(text, source, target, client, user_agent)
            translated_text = ' '.join(map(lambda x: x[0], translated_raw[0]))
        else:
            translated_text = __translate__(text, source, target, client, user_agent)

    elif mode == '2':
        if client == 't':
            intermediate_raw = __translate__(text, source, 'ja', client, user_agent)
            intermediate_text = ' '.join(map(lambda x: x[0], intermediate_raw[0]))
            translated_raw = __translate__(intermediate_text, 'ja', target, client, user_agent)
            translated_text = ' '.join(map(lambda x: x[0], translated_raw[0]))

        else:
            intermediate_text = __translate__(text, source, 'ja', client, user_agent)
            translated_text = __translate__(intermediate_text, 'ja', target, client, user_agent)

    else:
        return HTTPException('Invalid translation mode.', 400)

    return dict(
        id=None,
        request_id=None,
        intermediate_text=intermediate_text,
        intermediate_raw=intermediate_raw,
        translated_text=translated_text,
        translated_raw=translated_raw,
    )


@app.route('/dictionary')
def dictionary():
    keys = ('query', 'source', 'target')
    query, source, target = map(lambda k: request.args[k].strip(), keys)

    # TODO: URL encode

    if source == 'ko' and target == 'en':
        return redirect('http://endic.naver.com/search.nhn?searchOption=all&query={}'.format(query))
    elif source == 'en' and target == 'ko':
        return redirect('http://endic.naver.com/search.nhn?searchOption=all&query={}'.format(query))
    else:
        return 'Dictionary not available', 406


@app.route('/v1.0/test')
def test():
    """Produces arbitrary HTTP responses for debugging purposes."""

    status_code = int(request.args['status_code'])
    message = request.args['message']

    if 200 <= status_code < 600 and len(message) <= 8000:
        return message, status_code
    else:
        return '', 400


@app.route('/disclaimers')
def disclaimers():
    context = dict(
        version=__version__,
        locale=get_locale(),
    )
    return render_template('disclaimers.html', **context)


@app.teardown_request
def teardown_request(exception):
    """Refer http://flask.pocoo.org/docs/tutorial/dbcon/ for more details."""
    pass


@app.errorhandler(404)
def page_not_found(error):
    return render_template('404.html',
        version=__version__, message='Page Not Found'), 404


@app.route('/captcha', methods=['GET', 'POST'])
def captcha():
    return """
<!DOCTYPE html PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN">
<html>
<head><meta http-equiv="content-type" content="text/html; charset=utf-8"><meta name="viewport" content="initial-scale=1"><title>http://translate.google.com/translate_a/t?client=t</title></head>
<body style="font-family: arial, sans-serif; background-color: #fff; color: #000; padding:20px; font-size:18px;" onload="e=document.getElementById('captcha');if(e){e.focus();}">
<div style="max-width:400px;">
 <hr noshade size="1" style="color:#ccc; background-color:#ccc;"><br>
 
  To continue, please type the characters below:<br><br>
  <img src="/sorry/image?id=15806218432220984486&amp;hl=en" border="1" alt="Please enable images"><br><br><form action="CaptchaRedirect" method="get"><input type="hidden" name="continue" value="http://translate.google.com/translate_a/t?client=t"><input type="hidden" name="id" value="15806218432220984486"><input type="text" name="captcha" value="" id="captcha" size="12" style="font-size:16px; padding:3px 0 3px 5px; margin-left:0px;"><input type="submit" name="submit" value="Submit" style="font-size:18px; padding:4px 0;"><br><br><br></form>
  <hr noshade size="1" style="color:#ccc; background-color:#ccc;">
  
   <div style="font-size:13px;">
    <b>About this page</b><br><br>Our systems have detected unusual traffic from your computer network.  This page checks to see if it&#39;s really you sending the requests, and not a robot.  <a href="#" onclick="document.getElementById('infoDiv').style.display='block';">Why did this happen?</a><br><br>
    <div id="infoDiv" style="display:none; background-color:#eee; padding:10px; margin:0 0 15px 0; line-height:1.4em;">
     This page appears when Google automatically detects requests coming from your computer network which appear to be in violation of the <a href="//www.google.com/policies/terms/">Terms of Service</a>. The block will expire shortly after those requests stop.  In the meantime, solving the above CAPTCHA will let you continue to use our services.<br><br>This traffic may have been sent by malicious software, a browser plug-in, or a script that sends automated requests.  If you share your network connection, ask your administrator for help &mdash; a different computer using the same IP address may be responsible.  <a href="//support.google.com/websearch/answer/86640">Learn more</a><br><br>Sometimes you may be asked to solve the CAPTCHA if you are using advanced terms that robots are known to use, or sending requests very quickly.
    </div>
  
  
 
 
 IP address: 8.35.200.36<br>Time: 2013-11-17T10:28:53Z<br>URL: http://translate.google.com/translate_a/t?client=t<br>
 </div>
</div>
</body>
</html>
""".strip()
