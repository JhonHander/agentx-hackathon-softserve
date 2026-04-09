import bodyParser from 'body-parser';

export default (request, response, next) => {
  bodyParser.json({ inflate: false, limit: '2mb' })(request, response, next);
};
